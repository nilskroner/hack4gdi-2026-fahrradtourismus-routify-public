"""Prüft, ob das LLM (plus Plausibilisierung) typische Anfragen richtig in Parameter übersetzt.

Aufruf (Ollama muss laufen):  .venv/bin/python code/tests/test_llm_extraction.py
Optional: Modell wechseln mit LLM_MODEL=qwen3:4b

Jeder Fall prüft nur die angegebenen Felder. Listen werden als "enthält mindestens" geprüft.
Datumsangaben relativ zu "heute" werden zur Laufzeit berechnet.
"""
import asyncio
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "backend"))
from konfig import LLM_MODEL  # noqa: E402
from verstehen import extract_params  # noqa: E402

heute = date.today()


def naechster(wochentag):  # 0 = Montag
    d = (wochentag - heute.weekday()) % 7 or 7
    return (heute + timedelta(days=d)).isoformat()


FAELLE = [
    ("hamburg München 100km am tag mit dem Gravelbike, schlafen im Hotel",
     dict(start="Hamburg", ziel="München", tage=None, km_pro_tag=100, fahrrad="gravel", unterkunft_typ=["hotel"])),
    ("3 Tage von Dresden nach Magdeburg mit Kind, max. 50 km am Tag, abends Hotel",
     dict(start="Dresden", ziel="Magdeburg", tage=3, km_pro_tag=50, zielgruppe="familie", unterkunft_typ=["hotel"])),
    ("Elberadweg von Dresden bis Magdeburg in 4 Tagen",
     dict(start="Dresden", ziel="Magdeburg", tage=4, km_pro_tag=None)),
    ("Ich will mit meinen Kindern (6 und 9) von Bonn nach Koblenz radeln, maximal 40 km täglich, Campingplatz",
     dict(start="Bonn", ziel="Koblenz", km_pro_tag=40, zielgruppe="familie", unterkunft_typ=["camp_site"], tage=None)),
    ("Rennradtour Freiburg über Basel nach Konstanz, 120km/Tag",
     dict(start="Freiburg", ziel="Konstanz", zwischenziele=["Basel"], km_pro_tag=120, fahrrad="rennrad", tage=None)),
    ("Mit dem E-Bike ab Würzburg über Bamberg nach Bayreuth, 3 Tage, Pension",
     dict(start="Würzburg", ziel="Bayreuth", zwischenziele=["Bamberg"], tage=3, fahrrad="ebike", unterkunft_typ=["guest_house"])),
    ("Nächsten Samstag von Berlin nach Potsdam, ganz entspannt",
     dict(start="Berlin", ziel="Potsdam", startdatum=naechster(5), tage=None)),
    ("Morgen von Mainz nach Bingen",
     dict(start="Mainz", ziel="Bingen", startdatum=(heute + timedelta(days=1)).isoformat())),
    ("Von Kiel nach Flensburg, Übernachtung in der Jugendherberge",
     dict(start="Kiel", ziel="Flensburg", unterkunft_typ=["hostel"], startdatum=None)),
    ("Rentnerpaar, gemütlich, Lübeck nach Rostock, 30 km am Tag",
     dict(start="Lübeck", ziel="Rostock", zielgruppe="senioren", km_pro_tag=30, tage=None)),
    ("Mountainbike von Goslar nach Wernigerode",
     dict(start="Goslar", ziel="Wernigerode", fahrrad="mtb", tage=None, km_pro_tag=None)),
    ("Eine Woche von Frankfurt nach Heidelberg",
     dict(start="Frankfurt", ziel="Heidelberg", tage=7)),
    ("50km pro tag, 3 tage, start in passau, ziel regensburg",
     dict(start="Passau", ziel="Regensburg", tage=3, km_pro_tag=50)),
    ("Tour mit Anhänger und Kleinkind von Münster nach Osnabrück",
     dict(start="Münster", ziel="Osnabrück", zielgruppe="familie")),
    ("Ich bin schnell unterwegs, Hannover nach Bremen an einem Tag",
     dict(start="Hannover", ziel="Bremen", zielgruppe="sportlich", tage=1)),
    ("Fahrradtour von München zum Tegernsee, Übernachtung im Zelt",
     dict(start="München", ziel="Tegernsee", unterkunft_typ=["camp_site"])),
    ("Von Köln über Düsseldorf nach Duisburg, 2 Tage, Hotel oder Pension",
     dict(start="Köln", ziel="Duisburg", zwischenziele=["Düsseldorf"], tage=2, unterkunft_typ=["hotel", "guest_house"])),
    ("Wochenende ab Leipzig nach Halle, 2 Nächte im Hotel",
     dict(start="Leipzig", ziel="Halle", tage=3, unterkunft_typ=["hotel"])),
    ("zwei Tage Rhein von Koblenz nach Bonn mit dem Trekkingrad",
     dict(start="Koblenz", ziel="Bonn", tage=2, fahrrad="normal")),
    ("Ich möchte von Stuttgart nach Ulm, sportlich, 90 Kilometer pro Tag, Hotel",
     dict(start="Stuttgart", ziel="Ulm", zielgruppe="sportlich", km_pro_tag=90, unterkunft_typ=["hotel"], tage=None)),
    # Wunsch-POIs: allgemein (Auswahl anbieten) vs. konkret (Route darüber planen)
    ("Von Mainz nach Koblenz, 2 Tage, unterwegs brauche ich eine Fahrradwerkstatt",
     dict(start="Mainz", ziel="Koblenz", tage=2, poi_wuensche=[{"kategorie": "fahrradladen", "name": None}], poi_wuensche_anzahl=1)),
    ("Von Köln nach Bonn, irgendwo eine Werkstatt und einen Fahrradverleih",
     dict(start="Köln", ziel="Bonn", poi_wuensche=[{"kategorie": "fahrradladen", "name": None},
                                                    {"kategorie": "verleih", "name": None}], poi_wuensche_anzahl=2)),
    ("Von Leipzig nach Halle, 60 km am Tag",
     dict(start="Leipzig", ziel="Halle", poi_wuensche_anzahl=0, bahnhoefe_zeigen=False)),
    # Bahnhöfe nur auf Wunsch
    ("3 Tage Dresden nach Magdeburg mit Kind, zeig mir Bahnhöfe falls ich nicht mehr kann",
     dict(start="Dresden", ziel="Magdeburg", tage=3, bahnhoefe_zeigen=True)),
    ("Mainz nach Bingen, falls ich es mir nicht zutraue mit dem Zug zurück",
     dict(start="Mainz", ziel="Bingen", bahnhoefe_zeigen=True)),
    # Wettersuche: Zeitraum ist NICHT die Tourlänge
    ("Ich möchte anfragen, in den nächsten 7 Tagen wann mache ich am besten eine Tour von Bremen nach Hamburg, wenn es trocken ist",
     dict(start="Bremen", ziel="Hamburg", tage=None, wetter_suche={"tage": 7, "kriterium": "trocken"})),
    ("Wann ist nächste Woche gutes Wetter für 2 Tage von Mainz nach Koblenz?",
     dict(start="Mainz", ziel="Koblenz", tage=2, wetter_suche={"tage": 7, "kriterium": "gut"})),
    # Radfernweg
    ("Ich möchte von Hamburg nach Magdeburg den Elberadweg fahren",
     dict(start="Hamburg", ziel="Magdeburg", radweg="Elberadweg", zwischenziele_leer=True)),
    # Rundtour: km = Gesamtlänge, Ziel = Start
    ("Ich starte in Oldenburg und möchte 60 Kilometer fahren, Rundkurs",
     dict(start="Oldenburg", ziel="Oldenburg", rundtour=True, laenge_km=60, tage=None)),
    ("Kleine Runde ab Mainz, so 30 km mit Kindern",
     dict(start="Mainz", ziel="Mainz", rundtour=True, laenge_km=30, zielgruppe="familie")),
    # Vorlieben (werden aus dem Text erkannt und als BRouter-Parameter umgesetzt)
    ("Von Bonn nach Koblenz, möglichst flach, wenig Verkehr und am Wasser",
     dict(start="Bonn", ziel="Koblenz", vorlieben=["flach", "ruhig", "wasser"])),
    ("Mit Kinderanhänger von Münster nach Telgte", dict(start="Münster", ziel="Telgte", vorlieben=["keine_treppen"])),
    ("Mit dem Rennrad von Hamburg nach Lübeck, nur Asphalt",
     dict(start="Hamburg", ziel="Lübeck", fahrrad="rennrad", vorlieben=["asphalt"])),
    ("Von Würzburg nach Bamberg mit Fahrradwerkstatt unterwegs",
     dict(start="Würzburg", ziel="Bamberg", poi_wuensche=[{"kategorie": "fahrradladen", "name": None}])),
    # Wetterwunsch ohne Datum -> besten Tag suchen
    ("Von Bremen nach Oldenburg, an dem Tag mit Rückenwind",
     dict(start="Bremen", ziel="Oldenburg", wetter_suche={"tage": 7, "kriterium": "rueckenwind"})),
    ("Bei gutem Wetter von Mainz nach Bingen",
     dict(start="Mainz", ziel="Bingen", wetter_suche={"tage": 7, "kriterium": "gut"})),
    # Radfernweg nur mit Start: Ziel wird später entlang des Radwegs bestimmt
    ("3 Tage auf dem Weserradweg ab Hann. Münden", dict(start="Hann. Münden", tage=3, radweg="Weser-Radweg")),
]


# Nachträgliche Änderungen: (aktuelle Planung, Nachricht, erwartete Werte)
BASIS = dict(start="Mainz", ziel="Koblenz", zwischenziele=[], tage=2, km_pro_tag=None, zielgruppe="normal",
             fahrrad="normal", startdatum=None, unterkunft_typ=["hotel"], poi_wuensche=[], bahnhoefe_zeigen=False)
AENDERUNGEN = [
    (BASIS, "lieber 3 Tage und mit Campingplatz",
     dict(start="Mainz", ziel="Koblenz", tage=3, unterkunft_typ=["camp_site"])),
    (BASIS, "wir nehmen die Kinder mit", dict(start="Mainz", ziel="Koblenz", tage=2, zielgruppe="familie")),
    (BASIS, "doch nach Bonn statt Koblenz", dict(start="Mainz", ziel="Bonn", tage=2, unterkunft_typ=["hotel"])),
    (BASIS, "unterwegs noch eine Fahrradwerkstatt",
     dict(ziel="Koblenz", tage=2, poi_wuensche=[{"kategorie": "fahrradladen", "name": None}])),
    ({**BASIS, "poi_wuensche": [{"kategorie": "fahrradladen", "name": None}]}, "doch ohne Werkstatt, aber mit Fahrradverleih",
     dict(poi_wuensche=[{"kategorie": "verleih", "name": None}], poi_wuensche_anzahl=1)),
    (BASIS, "60 km am Tag", dict(ziel="Koblenz", km_pro_tag=60, tage=None)),
    (BASIS, "mit dem E-Bike", dict(ziel="Koblenz", tage=2, fahrrad="ebike")),
    (BASIS, "zeig mir noch ein paar Bahnhöfe zum Aussteigen", dict(ziel="Koblenz", tage=2, bahnhoefe_zeigen=True)),
    ({**BASIS, "bahnhoefe_zeigen": True}, "lieber 3 Tage", dict(tage=3, bahnhoefe_zeigen=True)),
    ({**BASIS, "bahnhoefe_zeigen": True}, "doch ohne Bahnhöfe", dict(tage=2, bahnhoefe_zeigen=False)),
    ({**BASIS, "zielgruppe": "familie", "unterkunft_typ": ["camp_site"]}, "Neue Tour: von Hamburg nach Lübeck",
     dict(start="Hamburg", ziel="Lübeck", zielgruppe="normal", unterkunft_typ=[], tage=None)),
]


def norm(v):
    return v.lower().replace(" (bei basel)", "").strip() if isinstance(v, str) else v


def pruefe(ist, soll):
    fehler = []
    for feld, erwartet in soll.items():
        if feld == "poi_wuensche_anzahl":
            if len(ist.get("poi_wuensche") or []) != erwartet:
                fehler.append(f"poi_wuensche: erwartet {erwartet} Einträge, ist {ist.get('poi_wuensche')}")
            continue
        if feld == "zwischenziele_leer":
            if ist.get("zwischenziele"):
                fehler.append(f"zwischenziele: erwartet leer, ist {ist.get('zwischenziele')}")
            continue
        if feld == "poi_wuensche":
            stamm = lambda n: " ".join(x[:5] for x in (n or "").lower().split())  # Beugung ignorieren
            vorhanden = [(w["kategorie"], stamm(w["name"])) for w in ist.get("poi_wuensche") or []]
            for e in erwartet:
                if (e["kategorie"], stamm(e["name"])) not in vorhanden:
                    fehler.append(f"poi_wuensche: erwartet {e}, ist {ist.get('poi_wuensche')}")
            continue
        wert = ist.get(feld)
        if isinstance(erwartet, list):
            fehlt = [e for e in erwartet if norm(e) not in [norm(w) for w in (wert or [])]]
            if fehlt:
                fehler.append(f"{feld}: erwartet {erwartet}, ist {wert}")
        elif isinstance(erwartet, str) and isinstance(wert, str):
            if not norm(wert).startswith(norm(erwartet)):
                fehler.append(f"{feld}: erwartet {erwartet!r}, ist {wert!r}")
        elif wert != erwartet:
            fehler.append(f"{feld}: erwartet {erwartet!r}, ist {wert!r}")
    return fehler


async def main():
    ok = 0
    t0 = time.time()
    async with httpx.AsyncClient() as client:
        for text, soll in FAELLE:
            ist = await extract_params(client, text)
            fehler = pruefe(ist, soll)
            if fehler:
                print(f"✗ {text}\n    " + "\n    ".join(fehler))
            else:
                ok += 1
                print(f"✓ {text}")
        print("\n— Nachträgliche Änderungen —")
        for vorher, text, soll in AENDERUNGEN:
            ist = await extract_params(client, text, dict(vorher))
            fehler = pruefe(ist, soll)
            if soll.get("unterkunft_typ") == [] and ist.get("unterkunft_typ"):
                fehler.append(f"unterkunft_typ: erwartet leer, ist {ist.get('unterkunft_typ')}")
            if fehler:
                print(f"✗ {text}\n    " + "\n    ".join(fehler))
            else:
                ok += 1
                print(f"✓ {text}")
    gesamt = len(FAELLE) + len(AENDERUNGEN)
    print(f"\n{ok}/{gesamt} richtig · Modell {LLM_MODEL} · {time.time() - t0:.0f} s")
    return ok == gesamt


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
