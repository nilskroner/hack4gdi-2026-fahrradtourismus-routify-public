"""Plausibilitätsprüfungen und Rückfragen (zu weit, zu kurz, außerhalb, Tage-Widerspruch)."""
import math
import re

from daten import BAHNHOEFE, IDX_BAHN
from geo import cumulative_km, haversine_km
from konfig import ROOT


SEGMENT_DIR = ROOT / "data" / "brouter" / "segments4"
KACHELN = set()
for _f in SEGMENT_DIR.glob("*.rd5"):
    _m = re.match(r"([EW])(\d+)_([NS])(\d+)", _f.stem)
    if _m:
        KACHELN.add(((1 if _m[1] == "E" else -1) * int(_m[2]), (1 if _m[3] == "N" else -1) * int(_m[4])))


def im_routing_gebiet(lon, lat):
    return (math.floor(lon / 5) * 5, math.floor(lat / 5) * 5) in KACHELN


# Realistische und maximal plausible Tagesdistanz (km)
TAGES_KM = {"familie": (40, 80), "senioren": (45, 90), "normal": (70, 150), "sportlich": (120, 250)}
TAGES_KM_RAD = {"rennrad": (140, 280), "gravel": (90, 180), "mtb": (50, 110), "ebike": (80, 160)}


def tages_km(params):
    if params.get("zielgruppe") in ("familie", "senioren"):
        return TAGES_KM[params["zielgruppe"]]
    return TAGES_KM_RAD.get(params.get("fahrrad")) or TAGES_KM.get(params.get("zielgruppe"), TAGES_KM["normal"])


def ja_option(params):
    return {"label": "Ja, war so gemeint", "params": {**params, "bestaetigt": True}}


def grenzort_richtung(start, ziel):
    """Letzter Ort mit Bahnhof (Deutschland) auf der Luftlinie Richtung Ziel, solange im Routing-Gebiet."""
    letzter = None
    schritte = max(2, int(haversine_km(start["lon"], start["lat"], ziel["lon"], ziel["lat"]) / 5))
    for i in range(schritte + 1):
        f = i / schritte
        lon = start["lon"] + (ziel["lon"] - start["lon"]) * f
        lat = start["lat"] + (ziel["lat"] - start["lat"]) * f
        if not im_routing_gebiet(lon, lat):
            break
        near = IDX_BAHN.near(lon, lat, 10)
        if near:
            letzter = near[0][1]["gemeinde"]
    return letzter


def rueckfrage_ausserhalb(params, points, aussen):
    namen = ", ".join(p["label"] for p in aussen)
    optionen = []
    ort = grenzort_richtung(points[0], aussen[-1]) if im_routing_gebiet(points[0]["lon"], points[0]["lat"]) else None
    if ort and ort.lower() != (params.get("start") or "").lower():
        optionen.append({"label": f"Bis {ort} (Richtung {aussen[-1]['name']})",
                         "params": {**params, "ziel": ort, "zwischenziele": [], "bestaetigt": False}})
    return {
        "params": params,
        "rueckfrage": (f"{namen} liegt außerhalb unseres Routing-Gebiets (Deutschland und Grenzregionen). "
                       "Meintest du einen Ort in Deutschland? Sonst kann ich bis kurz vor die Grenze planen:"
                       if optionen else
                       f"{namen} liegt außerhalb unseres Routing-Gebiets (Deutschland und Grenzregionen). "
                       "Bitte einen Ort in Deutschland nennen."),
        "optionen": optionen,
    }


def ziele_im_umkreis(start, distanz_km, anzahl=3):
    """Größere Orte (mit Hauptbahnhof) in passender Entfernung, möglichst in verschiedenen Richtungen."""
    luft = distanz_km / 1.25  # Radroute ist ca. 25 % länger als die Luftlinie
    kandidaten = []
    for b in BAHNHOEFE:
        if not re.search(r"\b(Hbf|Hauptbahnhof)\b", b["name"]):  # Hauptbahnhof = größere Stadt
            continue
        d = haversine_km(start["lon"], start["lat"], b["lon"], b["lat"])
        if 0.75 * luft <= d <= 1.25 * luft:
            richtung = math.degrees(math.atan2(b["lon"] - start["lon"], b["lat"] - start["lat"])) % 360
            kandidaten.append((abs(d - luft), int(richtung // (360 / anzahl)), b["gemeinde"], d))
    kandidaten.sort()
    gewaehlt, sektoren, namen = [], set(), set()
    for _, sektor, name, d in kandidaten:
        if sektor in sektoren or name in namen:
            continue
        sektoren.add(sektor); namen.add(name)
        gewaehlt.append((name, d))
        if len(gewaehlt) == anzahl:
            break
    return gewaehlt


def realismus_check(params, points, route):
    """Hinterfragt unrealistische Anfragen (zu weit pro Tag, zu kurz) mit Ja-Option und direkten Vorschlägen."""
    total = cumulative_km(route["coords"])[-1]
    tage, kpt = params.get("tage"), params.get("km_pro_tag")
    real, maximal = tages_km(params)
    gruppe = {"familie": "eine Familie", "senioren": "Senioren", "sportlich": "sportliche Fahrer"}.get(
        params.get("zielgruppe"), "eine normale Radtour")
    start, ziel = params.get("start"), params.get("ziel")

    # Zu weit pro Tag
    pro_tag = kpt or (total / tage if tage else None)
    if pro_tag and pro_tag > maximal:
        n = max(1, math.ceil(total / real))
        optionen = [ja_option(params),
                    {"label": f"{n} Tage à ca. {round(total / n)} km",
                     "params": {**params, "tage": n, "km_pro_tag": round(total / n), "bestaetigt": True}}]
        if tage:
            coords, km = route["coords"], cumulative_km(route["coords"])
            lon, lat, *_ = point_at_km(coords, km, tage * real)
            ort = ort_bei(lon, lat)
            if ort:
                optionen.append({"label": f"Kürzer: {tage} Tage à ca. {real} km, nur bis {ort}",
                                 "params": {**params, "ziel": ort, "km_pro_tag": real, "bestaetigt": True}})
        grund = (f"{round(pro_tag)} km pro Tag" if kpt else
                 f"{tage} {'Tag' if tage == 1 else 'Tage'} für ca. {round(total)} km wären {round(pro_tag)} km pro Tag")
        return {"params": params, "optionen": optionen,
                "rueckfrage": f"{start} → {ziel}: {grund}. Das ist für {gruppe} sehr viel "
                              f"(üblich sind ca. {real} km). War das so gemeint?"}

    # Zu kurz (z. B. "2 Tage in die Innenstadt")
    zu_kurz = total < 5 or (tage and tage > 1 and total / tage < 10)
    if zu_kurz:
        tage_n = tage or 1
        optionen = [ja_option(params)]
        for name, d in ziele_im_umkreis(points[0], tage_n * real):
            optionen.append({"label": f"{tage_n} {'Tag' if tage_n == 1 else 'Tage'} nach {name} (ca. {round(d * 1.25)} km)",
                             "params": {**params, "ziel": name, "zwischenziele": [], "bestaetigt": True}})
        dauer = f" für {tage} Tage" if tage and tage > 1 else ""
        return {"params": params, "optionen": optionen,
                "rueckfrage": f"{start} → {ziel} ist nur ca. {round(total, 1)} km lang{dauer}. "
                              "War das so gemeint? Sonst hier Vorschläge in passender Entfernung:"}
    return None


def point_at_km(coords, km, target):
    i = next((i for i, v in enumerate(km) if v >= target), len(km) - 1)
    return coords[i]


def ort_bei(lon, lat):
    """Ortsname nahe einem Punkt – offline über die Gemeinde des nächsten Bahnhofs."""
    near = IDX_BAHN.near(lon, lat, 15)
    return near[0][1]["gemeinde"] if near else None


def tage_konflikt(params, total):
    """Prüft, ob Tage und km/Tag zur Routenlänge passen. Gibt Rückfrage-Optionen zurück oder None."""
    tage, kpt = params.get("tage"), params.get("km_pro_tag")
    if params.get("bestaetigt") or not tage or not kpt:
        return None
    if abs(total / tage - kpt) <= 0.15 * kpt:  # bis 15 % Abweichung ist okay
        return None
    return True
