"""Aufbereitete Geodaten laden (Unterkünfte, Fahrrad-POIs, Bahnhöfe) und Indizes."""
import json

from geo import GridIndex
from konfig import PREPARED


def _load(name):
    path = PREPARED / name
    if not path.exists():
        raise SystemExit(f"{path} fehlt – zuerst code/scripts/prepare_data.py ausführen")
    return json.loads(path.read_text(encoding="utf-8"))


POIS = _load("pois.json")
BAHNHOEFE = _load("bahnhoefe.json")
IDX_UNTERKUNFT = GridIndex([p for p in POIS if p["kat"] == "unterkunft"])
IDX_RAD = GridIndex([p for p in POIS if p["kat"] != "unterkunft"])
IDX_BAHN = GridIndex(BAHNHOEFE)

# Wunsch-Stopps unterwegs ("mit Fahrradwerkstatt", "Fahrradverleih in …"): aus den OSM-Fahrrad-POIs
POI_KATEGORIEN = {"fahrradladen": "Fahrradwerkstatt", "verleih": "Fahrradverleih"}
POI_OSM_KAT = {"fahrradladen": ("fahrradladen", "reparatur"), "verleih": ("verleih",)}
IDX_STOPP = {k: GridIndex([{**p, "kat": k, "detail": {"reparatur": "Reparaturstation"}.get(p["kat"], p.get("typ"))}
                           for p in POIS if p["kat"] in kats and p.get("name")])
             for k, kats in POI_OSM_KAT.items()}

POI_ICON = {"wegpunkt": "📍", "fahrradladen": "🔧", "verleih": "🚲"}

# Wikidata-ID je amtlichem Gemeindeschlüssel (aus Wikidata P439, siehe prepare_data.py)
_wd = PREPARED / "wikidata_gemeinden.json"
WD_GEMEINDEN = json.loads(_wd.read_text(encoding="utf-8")) if _wd.exists() else {}


def gemeinde_von(lon, lat, radius_km=15):
    """Gemeinde (Name, AGS, Wikidata-ID) am Punkt – über den nächsten Bahnhof mit Gemeindeschlüssel."""
    for d, b in IDX_BAHN.near(lon, lat, radius_km):
        if b.get("ags"):
            wd = WD_GEMEINDEN.get(b["ags"], {})
            return {"name": b["gemeinde"], "ags": b["ags"], "ars": b.get("ars"), "wikidata": wd.get("qid")}
    return None
