"""Ortsname -> Koordinate.

1. Photon (komoot, OpenStreetMap) – öffentlich, bevorzugt Orte statt Straßen gleichen Namens
2. Zwischenspeicher (data/prepared/ortssuche_cache.json) – schon gesuchte Orte gehen ohne Internet
3. Offline-Rückfall: Ortsverzeichnis aus den eigenen Daten (Gemeinden der Bahnhöfe, Orte der POIs),
   falls Photon nicht erreichbar oder überlastet ist (beim Hackathon mehrfach: HTTP 503)
"""
import asyncio
import json
import re
import time

import httpx

from daten import BAHNHOEFE, POIS
from geo import haversine_km
from konfig import HTTP_HEADERS, PHOTON_URL, PREPARED

GENERISCH = ("innenstadt", "zentrum", "stadtmitte", "altstadt", "city", "hauptbahnhof", "hbf", "bahnhof")
CACHE_DATEI = PREPARED / "ortssuche_cache.json"
try:
    _CACHE = json.loads(CACHE_DATEI.read_text(encoding="utf-8")) if CACHE_DATEI.exists() else {}
except ValueError:
    _CACHE = {}


def _norm(s):
    return re.sub(r"[^a-z0-9äöüß]", "", (s or "").lower())


def _verzeichnis():
    """Ortsname -> Liste von (lon, lat, Gewicht): Mittelpunkt aller bekannten Punkte eines Orts, je Region getrennt."""
    gruppen = {}
    def add(name, lon, lat):
        k = (_norm(name), round(lat), round(lon))  # gleichnamige Orte in verschiedenen Regionen getrennt halten
        if k[0]:
            g = gruppen.setdefault(k, [0.0, 0.0, 0, name])
            g[0] += lon; g[1] += lat; g[2] += 1
    for b in BAHNHOEFE:
        add(b.get("gemeinde"), b["lon"], b["lat"])
    for p in POIS:
        add(p.get("ort"), p["lon"], p["lat"])
    out = {}
    for (n, _, _), (sx, sy, c, name) in gruppen.items():
        if c >= 2:
            out.setdefault(n, []).append({"lon": sx / c, "lat": sy / c, "gewicht": c, "name": name})
    return out


ORTE_OFFLINE = _verzeichnis()


def offline_suchen(name, near=None):
    """Ort aus dem eigenen Verzeichnis (ohne Internet). Bei mehreren gleichnamigen: nächster zu `near`, sonst größter."""
    treffer = ORTE_OFFLINE.get(_norm(name))
    if not treffer:
        return None
    if near:
        t = min(treffer, key=lambda x: haversine_km(near["lon"], near["lat"], x["lon"], x["lat"]))
    else:
        t = max(treffer, key=lambda x: x["gewicht"])
    return {"name": name, "label": t["name"], "lon": t["lon"], "lat": t["lat"],
            "land": "DE", "offline": True}


async def _photon(client, params):
    """Photon-Abfrage mit einer Wiederholung bei Überlastung (429/5xx)."""
    for versuch in range(2):
        try:
            r = await client.get(f"{PHOTON_URL}/api", params=params, headers=HTTP_HEADERS, timeout=12)
            if r.status_code in (429, 500, 502, 503, 504) and versuch == 0:
                await asyncio.sleep(1.0)
                continue
            r.raise_for_status()
            return r.json().get("features", [])
        except httpx.HTTPError:
            if versuch == 0:
                await asyncio.sleep(1.0)
                continue
            raise
    return []


def _cache_speichern():
    try:
        CACHE_DATEI.write_text(json.dumps(_CACHE, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


async def geocode(client, name, near=None, bezugsort=None):
    """Ortsname -> {name, label, lon, lat, land}. Bevorzugt Orte (Stadt/Ortsteil) statt Straßen gleichen Namens.
    near: Koordinate, in deren Nähe gesucht wird (z. B. Start beim Ziel).
    bezugsort: Ortsname für generische Begriffe wie "Innenstadt" (-> Mitte des Bezugsorts)."""
    q = name
    if bezugsort and name.lower().strip() in GENERISCH:
        ort = await geocode(client, bezugsort)
        return {**ort, "name": name, "label": f"{name} {ort['label']}"} if ort else None
    schluessel = f"{_norm(q)}|{round(near['lat'], 1) if near else ''}|{round(near['lon'], 1) if near else ''}"
    if schluessel in _CACHE:
        return {**_CACHE[schluessel], "name": name}
    base = {"q": q, "limit": 8, "lang": "de"}
    if near:
        base.update({"lat": near["lat"], "lon": near["lon"], "location_bias_scale": 0.1, "zoom": 6})
    try:
        feats = await _photon(client, {**base, "layer": ["city", "district", "locality"]})
        if feats and near:
            # Gleichnamiger Ort in Reichweite (< 150 km vom Start) schlägt den bekanntesten Ort gleichen Namens:
            # "Mainz -> Bingen" = Bingen am Rhein, aber "Oldenburg -> Rom" = Rom (Italien)
            nah = [f for f in feats
                   if (f["properties"].get("name") or "").lower().startswith(q.lower())
                   and haversine_km(near["lon"], near["lat"], *f["geometry"]["coordinates"]) < 150]
            # … außer der bekannteste Treffer ist eine Großstadt (place=city) mit genau diesem Namen:
            # "Hamburg -> Berlin" = die Hauptstadt, nicht das Dorf Berlin bei Seedorf (Schleswig-Holstein)
            top = feats[0]["properties"]
            grossstadt = top.get("osm_value") == "city" and (top.get("name") or "").lower() == q.lower()
            if nah and not grossstadt:
                # exakter Name vor Namensvarianten ("Koblenz" vor "Koblenz-Stolzenfels"), Orte vor sonstigen Treffern
                feats = sorted(nah, key=lambda f: (
                    (f["properties"].get("name") or "").lower() != q.lower(),
                    f["properties"].get("type") not in ("city", "town", "village"),
                    haversine_km(near["lon"], near["lat"], *f["geometry"]["coordinates"])))
        if not feats:
            feats = await _photon(client, base)  # z. B. "Mainz Hauptbahnhof"
    except httpx.HTTPError:
        return offline_suchen(name, near)  # Photon nicht erreichbar -> eigenes Verzeichnis
    if not feats:
        return offline_suchen(name, near)
    lon, lat = feats[0]["geometry"]["coordinates"]
    p = feats[0]["properties"]
    label = ", ".join(x for x in (p.get("name"), p.get("city") or p.get("state")) if x)
    ergebnis = {"name": name, "label": label, "lon": lon, "lat": lat, "land": p.get("countrycode"), "zeit": time.time()}
    _CACHE[schluessel] = ergebnis
    _cache_speichern()
    return ergebnis
