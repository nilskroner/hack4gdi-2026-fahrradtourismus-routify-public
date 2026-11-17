"""Bereitet Rohdaten aus data/ für den Prototyp auf.

Erzeugt in data/prepared/:
- bahnhoefe.json  Bahnhöfe/Haltepunkte mit Zugverkehr aus POI-Open (BKG), je Name zusammengefasst
- pois.json       Fahrrad-POIs und Unterkünfte (OpenStreetMap)
- wikidata_gemeinden.json  Wikidata-ID je amtlichem Gemeindeschlüssel (P439)

Die aufbereiteten Dateien liegen schon im Repo – das Skript braucht man nur zum Aktualisieren.
POI-Open (BKG, dl-de/by-2.0) wird bei Bedarf einmalig heruntergeladen; für die Bahnhöfe ist GDAL (ogr2ogr) nötig.

Aufruf: .venv/bin/python code/scripts/prepare_data.py
"""
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = DATA / "prepared"
OUT.mkdir(exist_ok=True)

# ogr2ogr (GDAL): aus PATH, sonst Postgres.app (macOS); überschreibbar mit OGR2OGR=/pfad/zu/ogr2ogr
OGR2OGR = (os.getenv("OGR2OGR") or shutil.which("ogr2ogr")
           or "/Applications/Postgres.app/Contents/Versions/latest/bin/ogr2ogr")


POI_OPEN_URL = "https://daten.gdz.bkg.bund.de/produkte/sonstige/poi-open/aktuell/poi-open.utm32s.shape.zip"
POI_OPEN_ZIP = DATA / "poi-open/poi-open.utm32s.shape.zip"


def prepare_bahnhoefe():
    # Haltestellen direkt aus dem Original-ZIP lesen (GDAL /vsizip/); entpackt wäre die .dbf 543 MB groß
    if not POI_OPEN_ZIP.exists():
        print(f"Lade BKG POI-Open (ca. 30 MB) von {POI_OPEN_URL}")
        POI_OPEN_ZIP.parent.mkdir(parents=True, exist_ok=True)
        tmp = POI_OPEN_ZIP.with_suffix(".tmp")
        urllib.request.urlretrieve(POI_OPEN_URL, tmp)
        tmp.replace(POI_OPEN_ZIP)
    shp = "/vsizip/" + str(POI_OPEN_ZIP) + "/poi-open/haltestellen/Haltestellen.shp"
    tmp = OUT / "_haltestellen_bahn.geojson"
    where = (
        "Verkehrsm LIKE '%Zugverkehr%' OR Verkehrsm LIKE '%S-Bahn%' "
        "OR Verkehrsm LIKE '%Fernverkehr%' OR Verkehrsm LIKE '%Hochgeschwindigkeit%'"
    )
    subprocess.run(
        [OGR2OGR, "-f", "GeoJSON", "-t_srs", "EPSG:4326", "-where", where,
         "-select", "Stop_ID,Name,Verkehrsm,Gemeinde,ARS", str(tmp), str(shp)],
        check=True,
    )
    feats = json.loads(tmp.read_text(encoding="utf-8"))["features"]
    tmp.unlink()

    # Ein Bahnhof steht pro Gleis/Verkehrsmittel mehrfach drin -> nach Name + Gemeinde zusammenfassen
    grouped = {}
    for f in feats:
        p = f["properties"]
        key = (p["Name"], p["Gemeinde"])
        lon, lat = f["geometry"]["coordinates"][:2]
        g = grouped.setdefault(key, {"name": p["Name"], "gemeinde": p["Gemeinde"], "ars": p.get("ARS"),
                                     "id": p["Stop_ID"], "verkehr": set(), "pts": []})
        g["verkehr"].update(v.strip() for v in (p["Verkehrsm"] or "").split(","))
        g["pts"].append((lon, lat))

    result = []
    for g in grouped.values():
        lon = sum(x for x, _ in g["pts"]) / len(g["pts"])
        lat = sum(y for _, y in g["pts"]) / len(g["pts"])
        ars = g.get("ars") or ""
        result.append({"name": g["name"], "gemeinde": g["gemeinde"], "id": g["id"],
                       # Amtlicher Gemeindeschlüssel (AGS) aus dem Regionalschlüssel: Land+RB+Kreis + Gemeinde
                       "ars": ars or None, "ags": (ars[:5] + ars[9:12]) if len(ars) == 12 else None,
                       "verkehr": sorted(v for v in g["verkehr"] if v),
                       "lon": round(lon, 6), "lat": round(lat, 6),
                       "quelle": "BKG POI-Open (Haltestellen)"})
    (OUT / "bahnhoefe.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"Bahnhöfe: {len(feats)} Einträge -> {len(result)} Stationen")


def prepare_wikidata_gemeinden():
    """Wikidata-ID je amtlichem Gemeindeschlüssel (Wikidata-Eigenschaft P439). Braucht Internet; ohne bleibt die alte Datei."""
    import urllib.parse
    import urllib.request
    q = 'SELECT ?item ?ags ?name WHERE { ?item wdt:P439 ?ags . OPTIONAL { ?item rdfs:label ?name FILTER(lang(?name)="de") } }'
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q})
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json",
                                                   "User-Agent": "routify-hackathon-prototyp/0.1"})
        rows = json.load(urllib.request.urlopen(req, timeout=120))["results"]["bindings"]
    except Exception as e:
        print(f"Wikidata nicht erreichbar ({e}) – vorhandene Zuordnung bleibt")
        return
    out = {r["ags"]["value"]: {"qid": r["item"]["value"].rsplit("/", 1)[-1], "name": r.get("name", {}).get("value")}
           for r in rows}
    (OUT / "wikidata_gemeinden.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"Wikidata: {len(out)} Gemeinden mit Gemeindeschlüssel")


def poi_kategorie(p):
    t, a, s = p.get("tourism"), p.get("amenity"), p.get("shop")
    if t in ("hotel", "guest_house", "hostel", "camp_site", "motel", "apartment", "chalet"):
        return "unterkunft"
    if s == "bicycle":
        return "fahrradladen"
    if a == "bicycle_repair_station":
        return "reparatur"
    if a == "bicycle_rental" or (s == "rental" and "bicycle" in json.dumps(p)):
        return "verleih"
    if a == "charging_station":
        return "laden"
    return None  # Abstellanlagen (200k+) bewusst weggelassen


UNTERKUNFT_TYPEN = ("hotel", "guest_house", "hostel", "camp_site", "motel")  # Ferienwohnungen bewusst nicht


def prepare_pois():
    result = []
    # 1) Unterkünfte aus dem OSM-Unterkunfts-Export (Punkte, "out center")
    seen_osm = set()
    unterkuenfte = []
    for f in json.loads((DATA / "osm-unterkuenfte/unterkuenfte_de_2026-11-13.geojson").read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        if p.get("tourism") not in UNTERKUNFT_TYPEN or not f.get("geometry"):
            continue
        c = shape(f["geometry"]).centroid
        seen_osm.add(p.get("@id") or p.get("id"))
        unterkuenfte.append({
            "kat": "unterkunft", "typ": p["tourism"], "name": p.get("name"),
            "lon": round(c.x, 6), "lat": round(c.y, 6),
            "osm": p.get("@id") or p.get("id"), "wikidata": p.get("wikidata"),
            "web": p.get("website") or p.get("contact:website"),
            "ort": p.get("addr:city"),
            "quelle": "OpenStreetMap (ODbL)",
        })

    result.extend(unterkuenfte)

    # 2) Fahrrad-POIs (und Hostels, die im Unterkunfts-Export fehlen) aus dem Fahrrad-Export
    src = DATA / "osm-fahrrad/fahrrad-poi_de_2026-11-13.geojson"
    feats = json.loads(src.read_text(encoding="utf-8"))["features"]
    for f in feats:
        p = f["properties"]
        kat = poi_kategorie(p)
        if not kat or not f.get("geometry"):
            continue
        if kat == "unterkunft" and (p.get("@id") in seen_osm or p.get("tourism") not in UNTERKUNFT_TYPEN):
            continue
        c = shape(f["geometry"]).centroid
        result.append({
            "kat": kat,
            "typ": p.get("tourism") or p.get("shop") or p.get("amenity"),
            "name": p.get("name"),
            "lon": round(c.x, 6), "lat": round(c.y, 6),
            "osm": p.get("@id"),
            "wikidata": p.get("wikidata"),
            "web": p.get("website") or p.get("contact:website"),
            "ort": p.get("addr:city"),
            "quelle": "OpenStreetMap (ODbL)",
        })
    (OUT / "pois.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    counts = {}
    for r in result:
        counts[r["kat"]] = counts.get(r["kat"], 0) + 1
    print(f"POIs: {len(result)} -> {counts}")


if __name__ == "__main__":
    prepare_bahnhoefe()
    prepare_pois()
    prepare_wikidata_gemeinden()
