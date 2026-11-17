"""Auswertung einer Route: Etappen, Unterkünfte, Höhen, Wege & Untergrund, POIs, Notausstiege."""
import hoehen
import math

from daten import IDX_BAHN, IDX_RAD, IDX_STOPP, IDX_UNTERKUNFT, POI_KATEGORIEN, WD_GEMEINDEN
from geo import peilung, ascend, downsample, haversine_km
from verstehen import _staemme


def unterkuenfte_waehlen(lon, lat, wunsch_typen, anzahl=3, radius_km=8):
    """Bis zu 3 Unterkünfte am Etappenende.
    Gewünschte Unterkunftsart zuerst (sonst verdrängt z. B. ein nahes Hotel den gewünschten Campingplatz –
    gefunden durch die SHACL-Prüfung); danach Name vorhanden, Nähe.
    Andere Arten nur als Ausweichoption, wenn es zu wenige der gewünschten gibt.
    Ferienwohnungen kommen ohne Wunsch nach den übrigen Arten."""
    kandidaten = IDX_UNTERKUNFT.near(lon, lat, radius_km)
    def score(t):
        d, it = t
        return (not (wunsch_typen and set(it.get("typen") or [it["typ"]]) & set(wunsch_typen)),
                it["typ"] == "apartment",
                not it.get("name"),
                d)
    gewaehlt, namen = [], set()
    for d, it in sorted(kandidaten, key=score):
        key = (it.get("name") or "").lower()
        if key and key in namen:
            continue
        namen.add(key)
        gewaehlt.append({**it, "dist_km": round(d, 1)})
        if len(gewaehlt) == anzahl:
            break
    return gewaehlt


def km_index_von(coords, pt, ab=0):
    """Index der Routenkoordinate, die einem Punkt am nächsten liegt (ab Index `ab`)."""
    best, best_i = 1e9, ab
    for i in range(ab, len(coords)):
        d = (coords[i][0] - pt["lon"]) ** 2 + (coords[i][1] - pt["lat"]) ** 2
        if d < best:
            best, best_i = d, i
    return best_i


def build_stages(coords, km, km_pro_tag, wunsch_typen=(), naechte=()):
    """Etappen nach km/Tag. Gewählte Übernachtungen (`naechte`, in Fahrtreihenfolge) sind feste Etappenenden;
    Abschnitte dazwischen werden bei Bedarf weiter nach km/Tag geteilt."""
    total = km[-1]
    # feste Enden (Index in coords) aus den Übernachtungen
    fest, ab = [], 0
    for u in naechte:
        i = km_index_von(coords, u, ab)
        if 0 < i < len(coords) - 1:
            fest.append((i, u))
            ab = i
    # Grenzen: zwischen festen Enden ggf. nach km/Tag teilen
    grenzen, prev = [], 0
    for i, u in fest + [(len(coords) - 1, None)]:
        laenge = km[i] - km[prev]
        teile = max(1, round(laenge / km_pro_tag))
        for k in range(1, teile):
            ziel_km = km[prev] + laenge * k / teile
            grenzen.append((next(j for j in range(prev, i + 1) if km[j] >= ziel_km), None))
        grenzen.append((i, u))
        prev = i
    n = len(grenzen)
    soll = total / n
    stages, start_i = [], 0
    for s, (end_i, nacht) in enumerate(grenzen, start=1):
        seg = coords[start_i:end_i + 1]
        eles = [c[2] for c in seg if len(c) > 2]
        end = coords[end_i]
        stage = {
            "nr": s,
            "von_km": round(km[start_i], 1), "bis_km": round(km[end_i], 1),
            "laenge_km": round(km[end_i] - km[start_i], 1),
            "anstieg_m": round(ascend(downsample(eles, 400))) if eles else None,
            "ende": {"lon": end[0], "lat": end[1]},
            "letzte": s == n,
            # Fahrtrichtung Start->Ende der Etappe (für Gegen-/Rückenwind); bei Rundtouren kaum aussagekräftig
            "richtung": round(peilung(coords[start_i][0], coords[start_i][1], end[0], end[1])),
        }
        if s < n and nacht:
            stage["uebernachtung"] = nacht  # vom Nutzer gewählt, Route führt hierher
            stage["unterkuenfte"] = [{**nacht, "dist_km": 0.0}]
        elif s < n:
            stage["unterkuenfte"] = unterkuenfte_waehlen(end[0], end[1], wunsch_typen)
        bahn = IDX_BAHN.near(end[0], end[1], 5)
        stage["bahnhof"] = {**bahn[0][1], "dist_km": round(bahn[0][0], 1)} if bahn else None
        stages.append(stage)
        start_i = end_i
    return stages, soll


def pois_along(coords, km, radius_km=0.5):
    seen, out, last = set(), [], -1.0
    for c, k in zip(coords, km):
        if k - last < 0.4:
            continue
        last = k
        for d, it in IDX_RAD.near(c[0], c[1], radius_km):
            key = (it["lon"], it["lat"])
            if key not in seen:
                seen.add(key)
                out.append({**it, "route_km": round(k, 1)})
    return out


def kunstbauten_km(messages, km_gesamt):
    """Brücken und Tunnel als (von_km, bis_km) – dort zeigt das Geländemodell nicht die Fahrbahnhöhe."""
    if len(messages) < 2:
        return []
    zeilen = [(int(r[3]), r[9]) for r in messages[1:]]
    summe = sum(d for d, _ in zeilen) / 1000 or 1
    faktor = km_gesamt / summe
    out, pos = [], 0.0
    for dist, tags in zeilen:
        t = dict(x.split("=", 1) for x in tags.split() if "=" in x)
        bau = t.get("bridge", "no") not in ("no",) or t.get("tunnel", "no") not in ("no", "culvert")
        if bau:
            von, bis = pos * faktor, (pos + dist / 1000) * faktor
            if out and von - out[-1][1] < 0.03:
                out[-1] = (out[-1][0], bis)
            else:
                out.append((von, bis))
        pos += dist / 1000
    return out


def hoehen_analyse(coords, km, stages, messages):
    """Höhenprofil, Anstieg und max. Steigung aus den BRouter-Höhen. None, wenn keine Höhen da sind."""
    erg = hoehen.profil(coords, km, kunstbauten_km(messages, km[-1]))
    if not erg:
        return None
    s, h, quelle = erg
    for st in stages:
        m = (s >= st["von_km"]) & (s <= st["bis_km"])
        if m.sum() >= 2:
            st["anstieg_m"] = round(hoehen.anstieg(h[m]))
            st["max_steigung"] = round(hoehen.max_steigung(s[m], h[m]), 1)
    return {
        "profil": downsample([[round(float(a), 2), round(float(b), 1)] for a, b in zip(s, h)], 600),
        "anstieg_m": round(hoehen.anstieg(h)),
        "max_steigung": round(hoehen.max_steigung(s, h), 1),
        "quelle": quelle,
    }


STRASSEN = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link", "trunk", "trunk_link"}
RUHIG = {"residential", "living_street", "service", "unclassified", "pedestrian", "road"}
GLATT = {"asphalt", "concrete", "concrete:plates", "concrete:lanes", "paved", "chipseal", "metal", "wood"}
PFLASTER = {"paving_stones", "sett", "cobblestone", "unhewn_cobblestone", "bricks", "grass_paver"}
SCHOTTER = {"compacted", "fine_gravel"}
UNBEFESTIGT = {"gravel", "pebblestone", "dirt", "ground", "earth", "grass", "mud", "sand", "unpaved", "rock", "woodchips"}


def wegtyp(t):
    hw = t.get("highway")
    if t.get("route") == "ferry":
        return "faehre"
    if hw == "cycleway" or (hw in ("path", "footway", "bridleway", "pedestrian", "track") and t.get("bicycle") == "designated"):
        return "radweg"
    if hw in STRASSEN:
        infra = " ".join(v for k, v in t.items() if k.startswith("cycleway"))
        return "radstreifen" if any(x in infra for x in ("lane", "track", "share_busway")) else "hauptstrasse"
    if hw in RUHIG:
        return "ruhig"
    if hw == "track":
        return "wirtschaftsweg"
    return "pfad"


def untergrund(t):
    sf = t.get("surface")
    if sf in GLATT:
        return "asphalt"
    if sf in PFLASTER:
        return "pflaster"
    if sf in SCHOTTER:
        return "schotter"
    if sf in UNBEFESTIGT:
        return "unbefestigt"
    tt = t.get("tracktype")
    if tt == "grade1":
        return "asphalt"
    if tt == "grade2":
        return "schotter"
    if tt in ("grade3", "grade4", "grade5"):
        return "unbefestigt"
    if t.get("highway") in STRASSEN | RUHIG | {"cycleway"}:
        return "asphalt"  # Straßen ohne Angabe sind in DE fast immer asphaltiert
    return "unbekannt"


def wege_analyse(messages, stages, coords, km):
    """Summiert Meter je Wegtyp/Untergrund (gesamt und je Etappe) und liefert Abschnitte für die Kartenfärbung.
    Abschnitte liegen auf der echten Routengeometrie (BRouter-Messages enthalten nur Wechselpunkte)."""
    if len(messages) < 2:
        return None
    gesamt = {"wegtyp": {}, "untergrund": {}}
    je_etappe = [{"wegtyp": {}, "untergrund": {}} for _ in stages]
    laeufe, pos_km = [], 0.0  # [von_km, bis_km, wegtyp, untergrund]
    for row in messages[1:]:
        dist = int(row[3])
        tags = dict(x.split("=", 1) for x in row[9].split() if "=" in x)
        wt, ug = wegtyp(tags), untergrund(tags)
        mitte = pos_km + dist / 2000
        for ziel in (gesamt, je_etappe[next((i for i, s in enumerate(stages) if mitte <= s["bis_km"]), len(stages) - 1)]):
            ziel["wegtyp"][wt] = ziel["wegtyp"].get(wt, 0) + dist
            ziel["untergrund"][ug] = ziel["untergrund"].get(ug, 0) + dist
        if laeufe and laeufe[-1][2] == wt and laeufe[-1][3] == ug:
            laeufe[-1][1] = pos_km + dist / 1000
        else:
            laeufe.append([pos_km, pos_km + dist / 1000, wt, ug])
        pos_km += dist / 1000

    # Läufe auf die Routengeometrie legen (km-Skala auf Geometrielänge normieren)
    faktor = km[-1] / pos_km if pos_km else 1
    abschnitte, i = [], 0
    schritt = max(1, len(coords) // 4000)  # Datenmenge begrenzen
    for von, bis, wt, ug in laeufe:
        von, bis = von * faktor, bis * faktor
        pts = []
        while i < len(coords) - 1 and km[i + 1] <= von:
            i += 1
        j = i
        while j < len(coords) and km[j] <= bis:
            if (j - i) % schritt == 0:
                pts.append([round(coords[j][1], 5), round(coords[j][0], 5)])
            j += 1
        if j < len(coords):
            pts.append([round(coords[j][1], 5), round(coords[j][0], 5)])  # an nächsten Abschnitt anschließen
        if len(pts) >= 2:
            abschnitte.append({"wt": wt, "ug": ug, "km": round(bis - von, 2), "pts": pts})
        i = max(i, j - 1)
    for s, e in zip(stages, je_etappe):
        s["wege"] = e
    return {**gesamt, "abschnitte": abschnitte}




def _linie_t(a, b, p):
    """Lage von p auf der Strecke a->b: (Anteil 0..1, Abstand km zur Linie)."""
    lat0 = math.radians((a["lat"] + b["lat"]) / 2)
    bx, by = (b["lon"] - a["lon"]) * 111.32 * math.cos(lat0), (b["lat"] - a["lat"]) * 110.57
    px, py = (p["lon"] - a["lon"]) * 111.32 * math.cos(lat0), (p["lat"] - a["lat"]) * 110.57
    l2 = bx * bx + by * by or 1
    t = max(0.0, min(1.0, (px * bx + py * by) / l2))
    return t, math.hypot(px - t * bx, py - t * by)


def poi_nach_name(kategorie, name, start, ziel):
    """Konkreten POI per Name finden (Kategorie zuerst, dann alle). Bei mehreren: der nächste zur Strecke."""
    teile = _staemme(name)
    alle = [p for k in IDX_STOPP for zelle in IDX_STOPP[k].cells.values() for p in zelle]
    for kats in ([kategorie], list(POI_KATEGORIEN)):
        treffer = [p for p in alle if p["kat"] in kats and p.get("name")
                   and all(x in p["name"].lower() for x in teile)]
        if treffer:
            from difflib import SequenceMatcher
            # ähnlichster Name zuerst ("Radhaus Meier" vor "Radhaus Meierhof"), dann Nähe zur Strecke
            return min(treffer, key=lambda p: (name.lower() not in p["name"].lower(),  # enthält den Namen ganz
                                               -round(SequenceMatcher(None, name.lower(), p["name"].lower()).ratio(), 2),
                                               _linie_t(start, ziel, p)[1]))
    return None


def _wp_key(p):
    return (p.get("typ"), (p.get("name") or "").lower())


def wegpunkte_ordnen(points, vias, reihenfolge=None):
    """Start + Zwischenpunkte + Ziel. Mit `reihenfolge` (vom Nutzer sortiert) wird diese übernommen;
    neue Punkte, die dort fehlen, werden nach ihrer Lage zwischen Start und Ziel einsortiert."""
    start, ziel = points[0], points[-1]
    pool = points[1:-1] + vias
    if not reihenfolge:
        return via_einfuegen(points, vias)
    geordnet = []
    for w in reihenfolge:
        treffer = next((p for p in pool if _wp_key(p) == _wp_key(w)), None)
        if treffer:
            geordnet.append(treffer)
            pool.remove(treffer)
    for p in pool:  # neu hinzugekommen -> nach Lage einsortieren
        t = _linie_t(start, ziel, p)[0]
        pos = next((i for i, q in enumerate(geordnet) if _linie_t(start, ziel, q)[0] > t), len(geordnet))
        geordnet.insert(pos, p)
    return [start, *geordnet, ziel]


def via_einfuegen(points, vias):
    """POI-Stopps nach ihrer Lage zwischen Start und Ziel in die Wegpunkte einsortieren."""
    if not vias:
        return points
    start, ziel = points[0], points[-1]
    mitte = [(_linie_t(start, ziel, p)[0], p) for p in points[1:-1] + vias]
    mitte.sort(key=lambda x: x[0])
    return [start, *[p for _, p in mitte], ziel]


def pois_entlang(index, coords, km, radius_km, schritt_km=0.3):
    """Alle Punkte eines Index im Umkreis der Route, mit kleinstem Abstand zur Route und Routen-km."""
    best = {}
    last = -1e9
    for c, k in zip(coords, km):
        if k - last < schritt_km:
            continue
        last = k
        for d, it in index.near(c[0], c[1], radius_km):
            key = id(it)
            if key not in best or d < best[key][0]:
                best[key] = (d, k, it)
    return sorted(best.values(), key=lambda x: x[1])


def poi_kandidaten(kategorie, coords, km, anzahl=6, radius_km=2.0):
    """Auswahl für allgemeine Wünsche ("ein Fahrradverleih"): über die Strecke verteilt, je Abschnitt der nächste."""
    treffer = pois_entlang(IDX_STOPP[kategorie], coords, km, radius_km, 0.5)
    if not treffer:
        return []
    total = km[-1] or 1
    faecher = {}
    for d, k, it in treffer:
        f = min(anzahl - 1, int(k / total * anzahl))
        if f not in faecher or d < faecher[f][0]:
            faecher[f] = (d, k, it)
    return [{**it, "route_km": round(k, 1), "dist_km": round(d, 1)}
            for d, k, it in sorted(faecher.values(), key=lambda x: x[1])]


def notausstiege(coords, km, radius_km=5.0):
    """Alle Bahnhöfe im Umkreis von 5 km um die Route, mit Abstand zur Route; Duplikate (< 400 m) zusammengefasst."""
    schritt = 0.25 if km[-1] < 300 else 0.5
    out = []
    for d, k, it in sorted(pois_entlang(IDX_BAHN, coords, km, radius_km, schritt), key=lambda x: x[0]):
        if any(haversine_km(it["lon"], it["lat"], o["lon"], o["lat"]) < 0.4 for o in out):
            continue
        out.append({"name": it["name"], "gemeinde": it["gemeinde"], "verkehr": it["verkehr"], "id": it["id"],
                    "ags": it.get("ags"), "ars": it.get("ars"), "gemeinde_wikidata": WD_GEMEINDEN.get(it.get("ags") or "", {}).get("qid"),
                    "lon": it["lon"], "lat": it["lat"], "route_km": round(k, 1), "dist_km": round(d, 1),
                    "quelle": it["quelle"]})
    return sorted(out, key=lambda x: x["route_km"])


# ---------------------------------------------------------------- Fahrzeit

# Reisegeschwindigkeit in der Ebene (km/h) – grobe Erfahrungswerte, Pausen nicht eingerechnet
TEMPO = {"familie": 12, "senioren": 14, "normal": 16, "sportlich": 22}
TEMPO_RAD = {"ebike": 20, "rennrad": 25, "gravel": 18, "mtb": 14}


def fahrzeit_h(km, hm, params):
    """Fahrzeit (Stunden) = km / Tempo + 10 Minuten je 100 Höhenmeter (E-Bike: 4 Minuten)."""
    if params.get("zielgruppe") in ("familie", "senioren"):
        v = TEMPO[params["zielgruppe"]]
    else:
        v = TEMPO_RAD.get(params.get("fahrrad")) or TEMPO.get(params.get("zielgruppe"), 16)
    je100 = 4 if params.get("fahrrad") == "ebike" else 10
    return round(km / v + (hm or 0) / 100 * je100 / 60, 1)
