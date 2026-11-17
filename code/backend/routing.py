"""Routing mit BRouter: Profile, Varianten, lange Strecken (Korridore), Radfernwege, Rundtouren."""
import re
import asyncio
import httpx
import math
import os
import radwege

from daten import IDX_BAHN
from geo import cumulative_km, haversine_km
from konfig import BROUTER_URL, ROOT


PROFILE = {"familie": "safety", "senioren": "safety", "normal": "trekking", "sportlich": "fastbike"}
PROFILE_RAD = {"gravel": "gravel", "rennrad": "fastbike", "mtb": "mtb"}  # Fahrradtyp schlägt Zielgruppe


PROFILE_ERLAUBT = ("trekking", "safety", "fastbike", "gravel", "mtb", "shortest")


# Welche Stellschrauben (%variable%) hat welches BRouter-Profil? (gravel kennt z. B. nicht alle)
_PROFIL_DIR = ROOT / "data" / "brouter" / "app" / "brouter-1.7.10" / "profiles2"
PROFIL_VARIABLEN = {p.stem: set(re.findall(r"%(\w+)%", p.read_text(encoding="utf-8", errors="ignore")))
                    for p in _PROFIL_DIR.glob("*.brf")} if _PROFIL_DIR.exists() else {}

# Vorlieben aus der Anfrage -> BRouter-Parameter
VORLIEBE_PARAMETER = {
    "flach": {"uphillcost": 80, "uphillcutoff": 1.0},
    "ruhig": {"avoid_unsafe": 1, "consider_traffic": 1},
    "leise": {"consider_noise": 1},
    "wasser": {"consider_river": 1},
    "wald": {"consider_forest": 1},
    "land": {"consider_town": 1},
    "radrouten": {"stick_to_cycleroutes": 1},
    "keine_treppen": {"allow_steps": 0},
    "keine_faehre": {"allow_ferries": 0},
}


def profil_mit_vorlieben(profil, vorlieben):
    """Profilname + Optionen als ein Text ("trekking|uphillcost=80|consider_river=1")."""
    erlaubt = PROFIL_VARIABLEN.get(profil)
    opts = {}
    for v in vorlieben or []:
        for k, wert in VORLIEBE_PARAMETER.get(v, {}).items():
            if erlaubt is None or k in erlaubt:
                opts[k] = wert
    return "|".join([profil] + [f"{k}={w}" for k, w in opts.items()])


def choose_profile(params):
    if params.get("profil") in PROFILE_ERLAUBT:  # Expertenmodus: fest gewähltes BRouter-Profil
        return params["profil"]
    if params.get("zielgruppe") == "familie":
        return "safety"  # Sicherheit geht bei Kindern vor
    return PROFILE_RAD.get(params.get("fahrrad")) or PROFILE.get(params.get("zielgruppe"), "trekking")


# BRouter bricht bei zu vielen gleichzeitigen Anfragen vom selben Client ältere ab ("thread-priority-watchdog").
BROUTER_SLOTS = asyncio.Semaphore(int(os.getenv("BROUTER_PARALLEL", "3")))
# Zwei Varianten (Hauptroute + eine Alternative). BRouter rechnet Alternative k, indem es die Routen 0…k-1
# erneut sucht und belegt – Alternative 2 kostete so 6–8 s statt 1,4 s für die Hauptroute.
ANZAHL_VARIANTEN = 2


async def brouter(client, points, profile, alt, versuche=2):
    lonlats = "|".join(f"{p['lon']:.6f},{p['lat']:.6f}" for p in points)
    name, *optionen = profile.split("|")  # Profil + Vorlieben, siehe profil_mit_vorlieben()
    extra = {f"profile:{o.split('=')[0]}": o.split("=")[1] for o in optionen if "=" in o}
    for _ in range(versuche):
        async with BROUTER_SLOTS:
            try:
                r = await client.get(f"{BROUTER_URL}/brouter", params={
                    "lonlats": lonlats, "profile": name, "alternativeidx": alt, "format": "geojson",
                    "profile:processUnusedTags": 1,  # auch bridge/tunnel ausgeben (für das Höhenprofil)
                    **extra,
                }, timeout=180)
            except httpx.HTTPError:
                return None  # z. B. Timeout bei sehr langen Strecken -> Variante fällt weg, Rest bleibt
        if r.status_code == 200:
            break
        print(f"BRouter {r.status_code}: {r.text[:200]}")
    else:
        return None
    f = r.json()["features"][0]
    return {"coords": f["geometry"]["coordinates"], "props": f["properties"]}


async def brouter_legs(client, points, profile):
    """Route über mehrere Wegpunkte als einzelne, parallel gerechnete Teilstücke (schneller bei langen Strecken)."""
    legs = await asyncio.gather(*(brouter(client, [a, b], profile, 0) for a, b in zip(points, points[1:])))
    if any(l is None for l in legs):
        return None
    coords, up, secs, msgs = [], 0, 0, []
    for l in legs:
        coords.extend(l["coords"] if not coords else l["coords"][1:])
        up += int(l["props"].get("filtered ascend", 0))
        secs += int(l["props"].get("total-time", 0))
        m = l["props"].get("messages") or []
        msgs.extend(m if not msgs else m[1:])  # Kopfzeile nur einmal
    return {"coords": coords, "props": {"filtered ascend": up, "total-time": secs, "messages": msgs}}


def korridor_punkte(start, ziel, versatz_km, n_via=2):
    """Zwischenorte auf der Luftlinie (bei 1/3, 2/3), seitlich versetzt und auf den nächsten Ort mit Bahnhof gelegt."""
    lat0 = math.radians((start["lat"] + ziel["lat"]) / 2)
    # in lokales km-System (x nach Osten, y nach Norden)
    dx = (ziel["lon"] - start["lon"]) * 111.32 * math.cos(lat0)
    dy = (ziel["lat"] - start["lat"]) * 110.57
    laenge = math.hypot(dx, dy) or 1
    nx, ny = -dy / laenge, dx / laenge  # Normale (links der Fahrtrichtung)
    vias = []
    for k in range(1, n_via + 1):
        f = k / (n_via + 1)
        x = dx * f + nx * versatz_km
        y = dy * f + ny * versatz_km
        lon = start["lon"] + x / (111.32 * math.cos(lat0))
        lat = start["lat"] + y / 110.57
        near = IDX_BAHN.near(lon, lat, 25)
        if near:
            b = near[0][1]
            vias.append({"name": b["gemeinde"], "label": b["gemeinde"], "lon": b["lon"], "lat": b["lat"]})
        else:
            vias.append({"name": "Wegpunkt", "label": "Wegpunkt", "lon": lon, "lat": lat})
    return vias


async def lange_strecke_varianten(client, points, profile, luftlinie, nur=None):
    """Korridore für lange Strecken (direkt, seitlich versetzt), jeweils in Teilstücken gerechnet."""
    start, ziel = points[0], points[-1]
    versatz = min(60, max(20, 0.12 * luftlinie))
    n_via = max(1, min(4, round(luftlinie / 220)))
    mitte = points[1:-1]  # vom Nutzer genannte Zwischenziele bleiben erhalten
    korridore = []
    for v in (0, versatz, -versatz)[:ANZAHL_VARIANTEN]:
        if mitte:
            korridore.append(points if v == 0 else None)
        else:
            korridore.append([start, *korridor_punkte(start, ziel, v, n_via), ziel])
    if nur is not None:  # nur die gewählte Variante rechnen, Reihenfolge/Index beibehalten
        korridore = [k if i == nur else None for i, k in enumerate(korridore)]
    async def nichts():
        return None
    routes = await asyncio.gather(*(brouter_legs(client, k, profile) if k else nichts() for k in korridore))
    return routes, korridore


async def radweg_variante(client, name, points, profile, hinweise):
    """Route entlang eines benannten Radwegs: Weg im Radweg-Netz suchen, als Wegpunkte an BRouter geben."""
    eintrag = radwege.INDEX.get(radwege._norm(name)) or radwege.erkennen(name)
    if not eintrag:
        hinweise.append(f"Den Radweg „{name}“ kenne ich nicht – normale Route geplant.")
        return None
    try:
        linien = await radwege.geometrie(client, eintrag)
    except Exception:
        hinweise.append(f"Der Verlauf des {eintrag['name']} ist gerade nicht abrufbar – normale Route geplant.")
        return None
    start, ziel = points[0], points[-1]
    p = radwege.pfad(linien, start, ziel)
    if not p or p["km"] < 2:
        hinweise.append(f"Start und Ziel liegen nicht am {eintrag['name']} – normale Route geplant.")
        return None
    for wo, abst in (("Start", p["start_abstand_km"]), ("Ziel", p["ziel_abstand_km"])):
        if abst > 3:
            hinweise.append(f"{wo} liegt {abst:.0f} km vom {eintrag['name']} entfernt – die Route führt dorthin.")
    # Radweg-Punkte + eigene Zwischenpunkte (Stopps, Übernachtungen) nach Lage entlang des Radwegs sortieren
    pfad = p["punkte"]
    def lage(pt):
        return min(range(0, len(pfad), 5), key=lambda i: (pfad[i][0] - pt["lon"]) ** 2 + (pfad[i][1] - pt["lat"]) ** 2)
    rw_pts = [{"lon": x, "lat": y, "name": "Radweg", "typ": "radweg"} for x, y in radwege.wegpunkte(pfad)]
    mitte = sorted(rw_pts + points[1:-1], key=lage)
    # Radweg-Punkte, die direkt neben einem eigenen Stopp liegen, weglassen (sonst Zickzack)
    eigene = points[1:-1]
    mitte = [m for m in mitte if m.get("typ") != "radweg"
             or all(haversine_km(m["lon"], m["lat"], e["lon"], e["lat"]) > 3 for e in eigene)]
    route = await brouter_legs(client, [start, *mitte, ziel], profile)
    if not route:
        hinweise.append(f"Routing entlang des {eintrag['name']} fehlgeschlagen – normale Route geplant.")
        return None
    return {"name": eintrag["name"], "route": route, "radweg_km": p["km"]}


RICHTUNGEN = (("Nord", 0), ("Ost", 90), ("Süd", 180), ("West", 270))


def _versetzt(p, km, grad):
    lat = p["lat"] + km * math.cos(math.radians(grad)) / 110.57
    lon = p["lon"] + km * math.sin(math.radians(grad)) / (111.32 * math.cos(math.radians(p["lat"])))
    return {"lon": lon, "lat": lat}


def _spannender_punkt(q, radius, schon):
    """Halt nahe q: Ort mit Bahnhof, sonst der Punkt selbst."""
    bahn = [b for d, b in IDX_BAHN.near(q["lon"], q["lat"], radius * 1.5) if b["gemeinde"] not in schon]
    if bahn:
        return {"typ": "ort", "name": bahn[0]["gemeinde"], "label": bahn[0]["gemeinde"],
                "lon": bahn[0]["lon"], "lat": bahn[0]["lat"]}
    return {"typ": "poi", "kat": "wegpunkt", "name": "Wegpunkt", "label": "📍 Wegpunkt", **q}


def _rund_punkte(start, laenge, grad, faktor, schon):
    """Drei Halte auf einem Kreis, der in Richtung `grad` vom Start liegt (im Uhrzeigersinn abgefahren)."""
    r = laenge / (2 * math.pi) / 1.25 * faktor  # Radstrecken sind ca. 25 % länger als der Kreis
    mitte = _versetzt(start, r, grad)
    radius = max(2.0, min(5.0, r * 0.5))
    out = []
    for winkel in (grad - 90, grad, grad + 90):
        pkt = _spannender_punkt(_versetzt(mitte, r, winkel), radius, schon | {o["name"] for o in out})
        out.append(pkt)
    return out


async def rund_varianten(client, start, laenge, profile, nur=None):
    """Rundtouren in vier Himmelsrichtungen; Länge wird einmal nachjustiert."""
    async def eine(i, name, grad):
        if nur is not None and nur != i:
            return None, None
        faktor, beste = 1.0, (None, None)
        for _ in range(3):
            vias = _rund_punkte(start, laenge, grad, faktor, set())
            route = await brouter_legs(client, [start, *vias, start], profile)
            if not route:
                faktor *= 0.85
                continue
            ist = cumulative_km(route["coords"])[-1]
            beste = (route, vias)
            if abs(ist / laenge - 1) <= 0.15:
                break
            faktor *= laenge / ist
        return beste
    erg = await asyncio.gather(*(eine(i, n, g) for i, (n, g) in enumerate(RICHTUNGEN)))
    return [e[0] for e in erg], [e[1] for e in erg], [n for n, _ in RICHTUNGEN]
