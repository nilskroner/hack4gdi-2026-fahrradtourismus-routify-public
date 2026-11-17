"""Straßenfotos von Mapillary entlang der Route.

Ablauf: Punkte im gleichen Abstand auf der Route → Mapillary-Abdeckungskacheln (Zoom 14, Ebene „image“)
→ nächstes Foto, das wirklich auf dem Track liegt (≤ 20 m) und möglichst in Fahrtrichtung blickt
→ Bilddetails (Vorschau-URL, Datum, Fotograf) über die Graph-API.
Die Bilder selbst liefert /api/foto/{id} über unseren Server aus: Der Browser spricht nie direkt mit Mapillary/Meta.
Die Bildersuche per bbox der Graph-API liefert derzeit nichts, darum der Weg über die Kacheln.
Lizenz der Fotos: CC BY-SA 4.0, Namensnennung „Mapillary“ und Fotograf.
"""
import asyncio
import math
import os
import time

import httpx

import mvt
from geo import haversine_km, peilung

TOKEN = os.getenv("MAPILLARY_TOKEN") or None
KACHEL_URL = "https://tiles.mapillary.com/maps/vtp/mly1_public/2/14/{x}/{y}"
GRAPH = "https://graph.mapillary.com"
Z = 14
MAX_ABSTAND_M = 20       # Foto muss auf dem Track liegen
FENSTER_KM = 0.6         # um jeden Stichprobenpunkt so weit entlang der Route suchen

_kacheln: dict = {}      # (x, y) -> Liste der Fotos
_details: dict = {}      # id -> Details
_bilder: dict = {}       # (id, groesse) -> bytes
_sperre = asyncio.Semaphore(6)
JAHR_MS = 365.25 * 24 * 3600 * 1000
JETZT_MS = time.time() * 1000


def aktiv():
    return bool(TOKEN)


def _kachel(lon, lat):
    n = 2 ** Z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


async def _kachel_laden(client, xy):
    if xy in _kacheln:
        return _kacheln[xy]
    async with _sperre:
        r = await client.get(KACHEL_URL.format(x=xy[0], y=xy[1]), params={"access_token": TOKEN}, timeout=20)
    fotos = []
    if r.status_code == 200 and r.content:
        fotos = [{"id": str(p["id"]), "lon": p["lon"], "lat": p["lat"], "pano": bool(p.get("is_pano")),
                  "richtung": p.get("compass_angle"), "zeit": p.get("captured_at"), "qualitaet": p.get("quality_score")}
                 for p in mvt.punkte(r.content, "image", Z, *xy)]
    if len(_kacheln) > 400:
        _kacheln.clear()
    _kacheln[xy] = fotos
    return fotos


def _abstand_m(p, a, b):
    """Abstand Punkt–Strecke in Metern (lokal eben, für kurze Abschnitte genau genug)."""
    k = math.cos(math.radians(p[1])) * 111320
    ax, ay, bx, by, px, py = a[0] * k, a[1] * 110540, b[0] * k, b[1] * 110540, p[0] * k, p[1] * 110540
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _winkel(a, b):
    d = abs((a - b) % 360)
    return min(d, 360 - d)


async def entlang(geometrie, von_km=0.0, bis_km=None, anzahl=18):
    """Bis zu `anzahl` Fotos gleichmäßig zwischen von_km und bis_km. geometrie: [[lat, lon], …] wie in /api/plan."""
    pts = [(c[1], c[0]) for c in geometrie]
    km = [0.0]
    for a, b in zip(pts, pts[1:]):
        km.append(km[-1] + haversine_km(a[0], a[1], b[0], b[1]))
    bis_km = min(bis_km if bis_km is not None else km[-1], km[-1])
    if len(pts) < 2 or bis_km <= von_km:
        return {"fotos": [], "auf_track": 0, "stichproben": 0, "fehler": None}
    schritt = max(1.0, (bis_km - von_km) / anzahl)
    ziele = [von_km + schritt * (i + 0.5) for i in range(int((bis_km - von_km) / schritt))]

    async with httpx.AsyncClient() as client:
        # benötigte Kacheln: alle Routenpunkte in den Suchfenstern
        fenster = []
        for z in ziele:
            idx = [i for i in range(len(pts) - 1) if km[i + 1] >= z - FENSTER_KM and km[i] <= z + FENSTER_KM]
            fenster.append(idx)
        xy = {_kachel(*pts[i]) for idx in fenster for i in idx} | {_kachel(*pts[idx[-1] + 1]) for idx in fenster if idx}
        await asyncio.gather(*(_kachel_laden(client, k) for k in xy), return_exceptions=True)

        gewaehlt, schon = [], set()
        for z, idx in zip(ziele, fenster):
            if not idx:
                continue
            kandidaten = {f["id"]: f for i in idx for k in (_kachel(*pts[i]), _kachel(*pts[i + 1])) for f in _kacheln.get(k, [])}
            lon0 = min(min(pts[i][0], pts[i + 1][0]) for i in idx) - 0.0004
            lon1 = max(max(pts[i][0], pts[i + 1][0]) for i in idx) + 0.0004
            lat0 = min(min(pts[i][1], pts[i + 1][1]) for i in idx) - 0.0003
            lat1 = max(max(pts[i][1], pts[i + 1][1]) for i in idx) + 0.0003
            bester = None
            for f in kandidaten.values():
                if f["id"] in schon or not (lon0 <= f["lon"] <= lon1 and lat0 <= f["lat"] <= lat1):
                    continue
                d, i = min((_abstand_m((f["lon"], f["lat"]), pts[i], pts[i + 1]), i) for i in idx)
                if d > MAX_ABSTAND_M:
                    continue
                fahrt = peilung(*pts[i], *pts[i + 1])
                blick = _winkel(f["richtung"], fahrt) if f["richtung"] is not None else 90
                # Bewertung: nah an der Route, nah am Stichprobenpunkt, Blick in Fahrtrichtung, kein Panorama, gute Qualität
                score = (d / MAX_ABSTAND_M + abs(km[i] - z) / FENSTER_KM + (blick / 60 if blick < 90 else 3)
                         + (1 if f["pano"] else 0) + (1 - (f["qualitaet"] or 0.5))
                         + min(3, max(0, (JETZT_MS - (f["zeit"] or 0)) / JAHR_MS - 2) / 3))  # ältere als 2 Jahre abwerten
                if bester is None or score < bester[0]:
                    bester = (score, f, km[i])
            if bester:
                schon.add(bester[1]["id"])
                gewaehlt.append({**bester[1], "km": round(bester[2], 1)})

        infos = await asyncio.gather(*(details(client, f["id"]) for f in gewaehlt), return_exceptions=True)
    out, fehler = [], None
    for f, info in zip(gewaehlt, infos):
        if isinstance(info, dict) and info.get("thumb_256_url"):
            out.append({"id": f["id"], "lon": f["lon"], "lat": f["lat"], "km": f["km"], "zeit": info.get("captured_at") or f["zeit"],
                        "fotograf": (info.get("creator") or {}).get("username"), "pano": f["pano"]})
        elif isinstance(info, Exception):
            fehler = str(info)
    return {"fotos": out, "auf_track": len(gewaehlt), "stichproben": len(ziele), "fehler": fehler if not out else None}


async def details(client, bild_id):
    if bild_id in _details:
        return _details[bild_id]
    async with _sperre:
        r = await client.get(f"{GRAPH}/{bild_id}", timeout=15, params={
            "access_token": TOKEN, "fields": "id,thumb_256_url,thumb_1024_url,captured_at,creator,compass_angle"})
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", "Mapillary-Fehler"))
    _details[bild_id] = j
    return j


async def bild(bild_id, gross=False):
    """Bilddaten (JPEG) – über unseren Server, damit der Browser keine Verbindung zu Meta aufbaut."""
    schluessel = (bild_id, gross)
    if schluessel in _bilder:
        return _bilder[schluessel]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        info = await details(client, bild_id)
        url = info.get("thumb_1024_url" if gross else "thumb_256_url")
        if not url:
            raise RuntimeError("kein Bild")
        async with _sperre:
            r = await client.get(url, timeout=20)
        r.raise_for_status()
    if len(_bilder) > 300:
        _bilder.clear()
    _bilder[schluessel] = r.content
    return r.content
