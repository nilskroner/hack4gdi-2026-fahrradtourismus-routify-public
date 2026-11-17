"""Benannte Radfernwege (Elberadweg, Weserradweg, D-Routen …) aus OpenStreetMap.

- Index:     data/radrouten/index.json (Name, ref, Netz aller OSM-Radrouten in DE)
- Geometrie: wird pro Radweg einmal über Overpass geladen und in data/radrouten/geometrie/ zwischengespeichert
- Routing:   aus den Abschnitten wird ein Wegenetz gebaut; darin wird der Weg von Start bis Ziel gesucht
             und als Folge von Wegpunkten an BRouter gegeben, damit die Route dem Radweg folgt.
"""
import heapq
import json
import math
import re
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "radrouten"
GEO_DIR = DIR / "geometrie"
OVERPASS = ("https://overpass-api.de/api/interpreter",          # Hauptserver
            "https://overpass.kumi.systems/api/interpreter")     # Ausweich-Server
QUELLE = "OpenStreetMap-Radrouten (ODbL)"

NEBEN = re.compile(r"alternativ|variante|umgehung|nebenroute|querverbindung|zubringer|abstecher|anbindung|"
                   r"verbindung|umleitung|hochwasser|fähre|alt\.", re.I)
SCHNITT = re.compile(r"\s+(abschnitt|teil|teilstrecke|etappe|links|rechts|linkselbisch|rechtselbisch|"
                     r"überwiegend|hauptroute|nord|süd|ost|west)\b.*$", re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9äöüß]", "", (s or "").lower())


def _aliase(name):
    """Mögliche Namen eines Radwegs aus dem OSM-Namen, z. B.
    "[D10] Elberadweg linkselbisch [Abschnitt J]" -> ["Elberadweg"],
    "EuroVelo 15 - Rheinradweg - Teilstrecke …" -> ["EuroVelo 15", "Rheinradweg"]."""
    n = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name or "")
    out = []
    for teil in re.split(r"\s+[-–]\s+|,", n):
        teil = SCHNITT.sub("", teil.strip()).strip(" -–")
        if len(_norm(teil)) >= 6 and not NEBEN.search(teil):
            out.append(teil)
    return out


def _lade_index():
    p = DIR / "index.json"
    if not p.exists():
        return {}, []
    rel = json.loads(p.read_text(encoding="utf-8"))["relationen"]
    idx = {}
    for r in rel:
        for a in _aliase(r["name"]):
            idx.setdefault(_norm(a), {"name": a, "ids": [], "neben": []})
            (idx[_norm(a)]["neben"] if NEBEN.search(r["name"]) else idx[_norm(a)]["ids"]).append(r["id"])
    return idx, rel


INDEX, RELATIONEN = _lade_index()
# Allgemeine Wörter sind keine Radweg-Namen ("lieber auf Radwegen" darf keine Route namens "Radweg" auslösen)
ALLGEMEIN = {"radweg", "radwege", "radwegen", "radroute", "radrouten", "radtour", "radfernweg", "radwanderweg",
             "fahrradroute", "fahrradtour", "radwegenetz", "hauptroute", "nebenroute", "rundtour", "rundroute"}
D_ROUTE = re.compile(r"\bd[\s-]?(?:route\s*)?(\d{1,2})\b", re.I)


def erkennen(text):
    """Benannten Radweg im Text finden. Rückgabe: {"name", "ids"} oder None."""
    t = _norm(text)
    # nur eindeutige Radweg-Namen (sonst würden Stadtnetze wie "Düsseldorf" als Radweg erkannt)
    treffer = [(len(k), v) for k, v in INDEX.items()
               if k in t and v["ids"] and k not in ALLGEMEIN and len(k) >= 8
               and any(w in k for w in ("radweg", "route", "velo", "tour", "radfernweg"))]
    if treffer:
        return max(treffer, key=lambda x: x[0])[1]
    # Radwege, die in OSM nur abschnittsweise je Bundesland existieren ("Oder-Neiße-Radweg Sachsen", "… Brandenburg")
    gruppen = {}
    for k, v in INDEX.items():
        if "radweg" in k and v["ids"]:
            stamm = k[:k.index("radweg") + 6]
            if len(stamm) >= 10 and stamm not in ALLGEMEIN and stamm in t:
                g = gruppen.setdefault(stamm, {"name": v["name"].split(" ")[0] if " " in v["name"] else v["name"], "ids": []})
                g["ids"] += v["ids"]
    if gruppen:
        stamm, g = max(gruppen.items(), key=lambda x: len(x[0]))
        return {"name": re.sub(r"(?i)(radweg).*$", r"\1", g["name"]), "ids": g["ids"]}
    m = D_ROUTE.search(text)
    if m:
        ref = f"D{int(m.group(1))}"
        ids = [r["id"] for r in RELATIONEN if r.get("ref") == ref and not NEBEN.search(r["name"])]
        if ids:
            return {"name": f"D-Route {int(m.group(1))}", "ids": ids}
    return None


async def geometrie(client, eintrag):
    """Linienzüge (je Weg eine Liste [lon, lat]) – aus dem Cache oder einmalig per Overpass."""
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    datei = GEO_DIR / f"{_norm(eintrag['name'])}.json"
    if datei.exists():
        return json.loads(datei.read_text(encoding="utf-8"))
    ids = ",".join(str(i) for i in eintrag["ids"])
    abfrage = f"[out:json][timeout:120];relation(id:{ids});way(r);out geom;"
    fehler = None
    for server in OVERPASS:  # öffentliche Server sind manchmal überlastet -> nächsten probieren
        try:
            r = await client.post(server, data={"data": abfrage}, headers={"User-Agent": "routify-prototype/0.1"},
                                  timeout=150)
            r.raise_for_status()
            break
        except httpx.HTTPError as e:
            fehler = e
    else:
        raise RuntimeError(f"Radweg-Geometrie nicht abrufbar ({fehler})")
    linien = [[[round(p["lon"], 6), round(p["lat"], 6)] for p in w["geometry"]]
              for w in r.json()["elements"] if w.get("type") == "way" and w.get("geometry")]
    datei.write_text(json.dumps(linien), encoding="utf-8")
    return linien


def _dist(a, b):
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def _netz(linien, luecke_km=1.5):
    """Wegenetz aus den OSM-Abschnitten: {knoten: [(nachbar, km)]}. Kleine Lücken (< luecke_km) werden überbrückt."""
    nachbarn = {}
    def kante(a, b, w):
        nachbarn.setdefault(a, []).append((b, w))
        nachbarn.setdefault(b, []).append((a, w))
    for linie in linien:
        knoten = [(round(p[0], 5), round(p[1], 5)) for p in linie]
        for a, b in zip(knoten, knoten[1:]):
            if a != b:
                kante(a, b, _dist(a, b))
    # Lücken: Endpunkte (Grad 1) mit nahen Knoten anderer Abschnitte verbinden (teurer, damit echte Wege Vorrang haben)
    raster = {}
    for k in nachbarn:
        raster.setdefault((int(k[0] * 50), int(k[1] * 50)), []).append(k)
    for k, ns in list(nachbarn.items()):
        if len(ns) != 1:
            continue
        gx, gy = int(k[0] * 50), int(k[1] * 50)
        nah = [(d, o) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for o in raster.get((gx + dx, gy + dy), [])
               if o != k and o != ns[0][0] and (d := _dist(k, o)) < luecke_km]
        for d, o in sorted(nah)[:3]:
            kante(k, o, d * 3)
    return nachbarn


def _dijkstra(nachbarn, sk, zk=None):
    best, vor, heap = {sk: 0.0}, {}, [(0.0, sk)]
    while heap:
        d, k = heapq.heappop(heap)
        if k == zk:
            break
        if d > best.get(k, 1e18):
            continue
        for n, w in nachbarn[k]:
            nd = d + w
            if nd < best.get(n, 1e18):
                best[n], vor[n] = nd, k
                heapq.heappush(heap, (nd, n))
    return best, vor


def endpunkt(linien, start=None, km=None):
    """Punkt auf dem Radweg, wenn nur der Start (oder gar nichts) bekannt ist.
    Mit km: der Punkt, der ab Start etwa km entlang des Radwegs entfernt liegt (sonst das Ende des Radwegs).
    Ohne Start: ein Ende des Radwegs als Start. Rückgabe: {"start": (lon, lat), "ziel": (lon, lat), "km"} oder None."""
    nachbarn = _netz(linien)
    if not nachbarn:
        return None
    # größte zusammenhängende Komponente nehmen (Index-Relationen enthalten manchmal lose Stücke)
    if start:
        sk = min(nachbarn, key=lambda k: _dist(k, (start["lon"], start["lat"])))
    else:
        beliebig = max(nachbarn, key=lambda k: len(nachbarn[k]))
        best, _ = _dijkstra(nachbarn, beliebig)
        sk = max(best, key=best.get)  # ein Ende des Radwegs
    best, _ = _dijkstra(nachbarn, sk)
    if km:
        # Punkte ≈ km entlang des Radwegs; davon der, der am weitesten vom Start weg liegt
        # (sonst landet man auf Schleifen, dem anderen Ufer oder Nebenästen wieder in Startnähe)
        kandidaten = [k for k in best if 0.8 * km <= best[k] <= 1.05 * km] or list(best)
        zk = max(kandidaten, key=lambda k: _dist(k, sk) - 0.2 * abs(best[k] - km))
    else:
        zk = max(best, key=lambda k: _dist(k, sk))
    return {"start": sk, "ziel": zk, "km": round(best[zk], 1)}


def pfad(linien, start, ziel, luecke_km=1.5):
    """Kürzester Weg im Radweg-Netz zwischen den Punkten, die Start und Ziel am nächsten liegen.
    Rückgabe: {"punkte": [[lon, lat], …], "km", "start_abstand_km", "ziel_abstand_km"} oder None."""
    nachbarn = _netz(linien, luecke_km)
    if not nachbarn:
        return None
    s = (start["lon"], start["lat"])
    z = (ziel["lon"], ziel["lat"])
    sk = min(nachbarn, key=lambda k: _dist(k, s))
    zk = min(nachbarn, key=lambda k: _dist(k, z))
    best, vor = _dijkstra(nachbarn, sk, zk)
    if zk not in best:
        return None
    weg, k = [zk], zk
    while k != sk:
        k = vor[k]
        weg.append(k)
    weg.reverse()
    return {"punkte": [list(p) for p in weg], "km": round(best[zk], 1),
            "start_abstand_km": round(_dist(sk, s), 1), "ziel_abstand_km": round(_dist(zk, z), 1)}


def wegpunkte(pfadpunkte, abstand_km=8.0, max_punkte=60):
    """Gleichmäßig verteilte Wegpunkte entlang des Pfads (ohne Anfang/Ende)."""
    gesamt = sum(_dist(a, b) for a, b in zip(pfadpunkte, pfadpunkte[1:]))
    abstand = max(abstand_km, gesamt / max_punkte)
    out, seit = [], 0.0
    for a, b in zip(pfadpunkte, pfadpunkte[1:]):
        seit += _dist(a, b)
        if seit >= abstand:
            out.append(b)
            seit = 0.0
    if out and _dist(out[-1], pfadpunkte[-1]) < abstand / 2:
        out.pop()  # nicht kurz vor dem Ende noch einen Punkt
    return out
