"""Wetter (DWD via Bright Sky): Tageswerte je Etappe und Suche nach dem besten Tag."""
import math
from datetime import date, timedelta
import asyncio

from geo import wind_relativ
from konfig import HTTP_HEADERS


async def wetter_reihe(client, lon, lat, von, bis):
    """Tageswerte (9–18 Uhr Ortszeit) von `von` bis `bis` für einen Punkt (Bright Sky / DWD)."""
    try:
        r = await client.get("https://api.brightsky.dev/weather", params={
            "lat": lat, "lon": lon, "date": von.isoformat(), "last_date": (bis + timedelta(days=1)).isoformat(),
            "tz": "Europe/Berlin"}, headers=HTTP_HEADERS, timeout=20)
        r.raise_for_status()
        stunden = r.json()["weather"]
    except Exception:
        return {}
    tage = {}
    for h in stunden:
        if 9 <= int(h["timestamp"][11:13]) <= 18:
            tage.setdefault(h["timestamp"][:10], []).append(h)
    out = {}
    for d, hs in tage.items():
        temps = [h["temperature"] for h in hs if h["temperature"] is not None]
        winds = [h["wind_speed"] for h in hs if h["wind_speed"] is not None]
        probs = [h.get("precipitation_probability") for h in hs if h.get("precipitation_probability") is not None]
        dirs = [h["wind_direction"] for h in hs if h.get("wind_direction") is not None]
        sx = sum(math.sin(math.radians(x)) for x in dirs); cx = sum(math.cos(math.radians(x)) for x in dirs)
        out[d] = {"wind_richtung": round((math.degrees(math.atan2(sx, cx)) + 360) % 360) if dirs else None,
                  "regen_mm": round(sum(h["precipitation"] or 0 for h in hs), 1),
                  "regen_wahrsch": max(probs) if probs else None,
                  "t_max": round(max(temps)) if temps else None, "wind_kmh": round(max(winds)) if winds else None,
                  "sonne_min": round(sum(h.get("sunshine") or 0 for h in hs))}
    return out


def tag_bewertung(w, kriterium):
    """Kleiner = besser. Trocken: Regen zählt fast allein; gut: auch Wärme, Wind, Sonne."""
    if not w:
        return 99
    regen = w["regen_mm"] * 3 + (w["regen_wahrsch"] or 0) / 20
    if kriterium == "rueckenwind":  # Gegenwind-Anteil (km/h) entlang der Etappe; Rückenwind gibt Bonus
        return regen + (w.get("gegenwind_kmh") or 0) / 4
    if kriterium == "trocken":
        return regen + (w["wind_kmh"] or 0) / 50
    kalt = max(0, 15 - (w["t_max"] or 0)) / 3
    return regen + kalt + max(0, (w["wind_kmh"] or 0) - 25) / 10 - (w["sonne_min"] or 0) / 240


async def besten_tag_finden(client, etappen, start, suche):
    """Prüft jeden möglichen Starttag im Zeitraum (mehrtägig: alle Etappentage) und wählt den besten."""
    n = len(etappen)
    erster = date.today() + timedelta(days=1) if datetime_now_hour() >= 15 else date.today()
    letzter = min(date.today() + timedelta(days=9), erster + timedelta(days=suche["tage"] - 1))
    punkte = [start] + [s["ende"] for s in etappen]  # Etappe i: Wetter an Start- und Endpunkt
    reihen = await asyncio.gather(*(wetter_reihe(client, p["lon"], p["lat"], erster, letzter + timedelta(days=n))
                                    for p in punkte))
    kandidaten = []
    for offset in range((letzter - erster).days + 1):  # jeder mögliche Starttag im Zeitraum
        tag = erster + timedelta(days=offset)
        tage_w = []
        for i in range(n):  # Etappe i am Tag tag+i, Wetter an Start- und Endpunkt der Etappe
            d = (tag + timedelta(days=i)).isoformat()
            a, b = reihen[i].get(d), reihen[i + 1].get(d)
            if not a or not b:
                tage_w = None  # keine Vorhersage (z. B. > 10 Tage)
                break
            tage_w.append({"datum": d, "regen_mm": max(a["regen_mm"], b["regen_mm"]),
                           "regen_wahrsch": max(a["regen_wahrsch"] or 0, b["regen_wahrsch"] or 0),
                           "t_max": max(a["t_max"] or -99, b["t_max"] or -99),
                           "wind_kmh": max(a["wind_kmh"] or 0, b["wind_kmh"] or 0),
                           "sonne_min": round(((a["sonne_min"] or 0) + (b["sonne_min"] or 0)) / 2),
                           "gegenwind_kmh": wind_relativ(etappen[i].get("richtung"), b.get("wind_richtung"),
                                                         max(a["wind_kmh"] or 0, b["wind_kmh"] or 0))[0]})
        if not tage_w:
            continue
        kandidaten.append({"start": tag.isoformat(),
                           "score": round(sum(tag_bewertung(w, suche["kriterium"]) for w in tage_w), 2),
                           "tage": tage_w, "regen_mm": round(sum(w["regen_mm"] for w in tage_w), 1),
                           "regen_wahrsch": max(w["regen_wahrsch"] for w in tage_w),
                           "t_max": max(w["t_max"] for w in tage_w), "wind_kmh": max(w["wind_kmh"] for w in tage_w),
                           # Wind in Fahrtrichtung im Mittel (+ = Gegenwind, − = Rückenwind)
                           "gegenwind_kmh": round(sum(w["gegenwind_kmh"] or 0 for w in tage_w) / len(tage_w), 1)})
    if not kandidaten:
        return None
    bester = min(kandidaten, key=lambda k: (k["score"], k["start"]))
    for k in kandidaten:
        k["bester"] = k is bester
        k["trocken"] = k["regen_mm"] <= 0.5
    return {"kriterium": suche["kriterium"], "zeitraum_tage": suche["tage"], "bester": bester["start"],
            "kandidaten": kandidaten, "quelle": "DWD via Bright Sky"}


def datetime_now_hour():
    from datetime import datetime
    return datetime.now().hour


async def weather(client, lon, lat, day):
    if (day - date.today()).days > 9:
        return {"hinweis": "Keine Vorhersage (mehr als 10 Tage)"}
    try:
        r = await client.get("https://api.brightsky.dev/weather", params={
            "lat": lat, "lon": lon, "date": day.isoformat(),
            "last_date": (day + timedelta(days=1)).isoformat(),
        }, headers=HTTP_HEADERS, timeout=15)
        r.raise_for_status()
        hours = [w for w in r.json()["weather"] if 9 <= int(w["timestamp"][11:13]) <= 18]
    except Exception:
        return {"hinweis": "Wetter nicht abrufbar"}
    if not hours:
        return {"hinweis": "Keine Daten"}
    temps = [h["temperature"] for h in hours if h["temperature"] is not None]
    winds = [h["wind_speed"] for h in hours if h["wind_speed"] is not None]
    rain = sum(h["precipitation"] or 0 for h in hours)
    dirs = [h["wind_direction"] for h in hours if h["wind_direction"] is not None]
    conds = [h["condition"] for h in hours if h.get("condition")]
    return {
        "datum": day.isoformat(),
        "t_min": round(min(temps)) if temps else None,
        "t_max": round(max(temps)) if temps else None,
        "regen_mm": round(rain, 1),
        "wind_kmh": round(max(winds)) if winds else None,
        "wind_richtung": round(sum(dirs) / len(dirs)) if dirs else None,
        "lage": max(set(conds), key=conds.count) if conds else None,
        "quelle": "DWD via Bright Sky",
    }
