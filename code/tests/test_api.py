"""End-to-End-Tests gegen den laufenden Server (http://localhost:8000).

Aufruf:  .venv/bin/python code/tests/test_api.py           (alle Fälle, ca. 2–3 min)
         .venv/bin/python code/tests/test_api.py schnell   (ohne LLM-Fälle, nur Parameter)

Voraussetzung: Backend, BRouter und Ollama laufen. Prüft Struktur und Plausibilität der Antworten,
nicht exakte Werte (Wetter, Routen können sich ändern).
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASIS = "http://localhost:8000"
ERGEBNISSE = []


def aufruf(pfad, daten=None, methode=None, cookie=None):
    req = urllib.request.Request(BASIS + pfad, data=json.dumps(daten).encode() if daten is not None else None,
                                 method=methode or ("POST" if daten is not None else "GET"),
                                 headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers.get("set-cookie")
    except urllib.error.HTTPError as e:
        roh = e.read() or b"{}"
        try:
            return e.code, json.loads(roh), None
        except ValueError:
            return e.code, {"fehler": roh.decode("utf-8", "replace")[:200]}, None


def fall(name, func):
    t = time.time()
    try:
        func()
        ERGEBNISSE.append((True, name, time.time() - t, ""))
        print(f"✓ {name} ({time.time() - t:.1f} s)")
    except Exception as e:
        ERGEBNISSE.append((False, name, time.time() - t, str(e)))
        print(f"✗ {name}: {e}")


def plan(text=None, params=None, vorher=None, cookie=None):
    code, d, _ = aufruf("/api/plan", {"text": text or "", "params": params, "vorher": vorher}, cookie=cookie)
    assert code == 200, f"HTTP {code}: {d}"
    assert "fehler" not in d, d.get("fehler")
    return d


def hat_route(d, min_var=1):
    assert "alternativen" in d, f"keine Route: {d.get('rueckfrage')}"
    assert len(d["alternativen"]) >= min_var, f"nur {len(d['alternativen'])} Varianten"
    a = d["alternativen"][0]
    assert a["laenge_km"] > 0 and a["etappen"], "leere Route"
    assert a["hoehenprofil"], "kein Höhenprofil"
    return a


# ---------------------------------------------------------------- Fälle

def t_health():
    code, d, _ = aufruf("/api/health")
    assert code == 200 and d["ollama"] == "ok" and d["brouter"] == "ok", d


def t_normal():
    d = plan(params={"start": "Mainz", "ziel": "Koblenz", "tage": 2, "zielgruppe": "normal", "fahrrad": "normal",
                     "unterkunft_typ": ["hotel"], "bestaetigt": True})
    a = hat_route(d, 2)
    assert len(a["etappen"]) == 2
    assert a["etappen"][0]["unterkuenfte"], "keine Unterkünfte"
    assert a["wege"]["wegtyp"], "keine Wegeanalyse"
    assert "SRTM" in a["hoehen_quelle"]
    assert a["max_steigung"] is not None and a["etappen"][0].get("anstieg_m") is not None, "Höhenprofil fehlt"
    assert a["notausstiege"], "keine Notausstiege berechnet"


def t_text():
    d = plan("3 Tage von Dresden nach Magdeburg mit Kind, 80 km am Tag")
    assert d["params"]["zielgruppe"] == "familie" and d["params"]["tage"] == 3
    a = hat_route(d)
    assert a["profil"] == "safety"


def t_grossstadt_vor_dorf():
    # „Berlin“ ab Hamburg ist die Hauptstadt, nicht das Dorf Berlin bei Seedorf (Nähe-Regel der Ortssuche)
    d = plan(params={"start": "Hamburg", "ziel": "Berlin", "zielgruppe": "normal", "fahrrad": "normal", "bestaetigt": True})
    a = hat_route(d)
    assert a["laenge_km"] > 250, f"nur {a['laenge_km']} km – falsches Berlin?"


def t_rueckfrage_tage():
    d = plan("3 Tage von Dresden nach Magdeburg mit Kind, 50 km am Tag")
    assert d.get("rueckfrage") and d.get("optionen"), "keine Rückfrage bei 3×50 km für 250 km"


def t_ausserhalb():
    d = plan("2 Tage von Oldenburg nach Rom")
    assert d.get("rueckfrage") and "außerhalb" in d["rueckfrage"]


def t_radweg():
    d = plan(params={"start": "Hamburg", "ziel": "Lüneburg", "radweg": "Elberadweg", "zielgruppe": "normal",
                     "fahrrad": "normal", "bestaetigt": True})
    hat_route(d)
    assert d.get("radweg") and d["radweg"]["name"] == "Elberadweg"


def t_radweg_ohne_ziel():
    d = plan(params={"start": "Dresden", "ziel": None, "radweg": "Elberadweg", "tage": 2, "zielgruppe": "normal",
                     "fahrrad": "normal", "bestaetigt": True})
    a = hat_route(d)
    assert d["params"]["ziel"], "kein Ziel bestimmt"
    assert 70 <= a["laenge_km"] <= 140, f"{a['laenge_km']} km statt ~100 (2 Tage × 50 km)"


def t_vorlieben():
    d = plan(params={"start": "Mainz", "ziel": "Bingen", "vorlieben": ["flach", "ruhig"], "zielgruppe": "normal",
                     "fahrrad": "normal", "bestaetigt": True})
    a = hat_route(d, 2)
    assert "uphillcost=80" in (a.get("profil_optionen") or []), a.get("profil_optionen")
    assert a.get("fahrzeit_h"), "keine Fahrzeit"


def t_rundtour():
    d = plan(params={"start": "Oldenburg", "ziel": "Oldenburg", "rundtour": True, "laenge_km": 40, "km_pro_tag": 40,
                     "zielgruppe": "normal", "fahrrad": "normal", "bestaetigt": True})
    hat_route(d, 3)
    for a in d["alternativen"]:
        assert 25 <= a["laenge_km"] <= 60, f"Rundtour {a['laenge_km']} km statt ~40"
        assert a.get("titel", "").startswith("Richtung")


def t_wetter():
    d = plan(params={"start": "Bremen", "ziel": "Oldenburg", "zielgruppe": "normal", "fahrrad": "normal",
                     "wetter_suche": {"tage": 5, "kriterium": "trocken"}, "bestaetigt": True})
    hat_route(d)
    w = d.get("wetter_wahl")
    assert w and w["kandidaten"] and any(k["bester"] for k in w["kandidaten"])
    assert d["startdatum"] == next(k["start"] for k in w["kandidaten"] if k.get("gewaehlt"))


def t_poi_auswahl_und_via():
    d = plan(params={"start": "Mainz", "ziel": "Bingen", "zielgruppe": "normal", "fahrrad": "normal",
                     "poi_wuensche": [{"kategorie": "fahrradladen", "name": None}], "bestaetigt": True})
    hat_route(d)
    assert d["poi_auswahl"] and d["poi_auswahl"][0]["kandidaten"], "keine Fahrradwerkstatt-Vorschläge"
    k = d["poi_auswahl"][0]["kandidaten"][0]
    p = {**d["params"], "via_pois": [{"kat": "fahrradladen", "name": k["name"], "lon": k["lon"], "lat": k["lat"]}],
         "nur_variante": d["alternativen"][0]["idx"]}
    d2 = plan(params=p)
    assert len(d2["alternativen"]) == 1, "andere Varianten nicht ausgeblendet"
    assert any(w["typ"] == "poi" for w in d2["wegpunkte"]), "Stopp fehlt in Wegpunkten"


def t_uebernachtung():
    d = plan(params={"start": "Mainz", "ziel": "Koblenz", "tage": 2, "zielgruppe": "normal", "fahrrad": "normal",
                     "bestaetigt": True})
    u = d["alternativen"][0]["etappen"][0]["unterkuenfte"][0]
    p = {**d["params"], "uebernachtungen": [{**u, "typ": "nacht"}], "wegpunkte": [{"typ": "nacht", "name": u["name"]}]}
    d2 = plan(params=p)
    assert d2["alternativen"][0]["etappen"][0].get("uebernachtung", {}).get("name") == u["name"]


def t_aenderung():
    d = plan("Von Mainz nach Koblenz, 2 Tage, Hotel")
    d2 = plan("lieber 3 Tage und mit Campingplatz", vorher=d["params"])
    assert d2["params"]["tage"] == 3 and d2["params"]["unterkunft_typ"] == ["camp_site"]
    assert d2["params"]["ziel"] == "Koblenz"


def t_konto():
    name = f"apitest{int(time.time())}"
    code, d, ck = aufruf("/api/konto/registrieren", {"name": name, "passwort": "geheim123"})
    assert code == 200 and ck, d
    cookie = ck.split(";")[0]
    code, d, _ = aufruf("/api/konto/voreinstellungen", {"zielgruppe": "familie", "km_pro_tag": 40}, "PUT", cookie)
    assert code == 200
    code, d, _ = aufruf("/api/touren", {"name": "Test", "params": {"start": "A", "ziel": "B"}}, cookie=cookie)
    assert code == 200 and d["id"]
    code, d2, _ = aufruf("/api/touren", cookie=cookie)
    assert any(t["id"] == d["id"] for t in d2["touren"])
    code, _, _ = aufruf("/api/touren")
    assert code == 401, "Touren ohne Anmeldung sichtbar"
    aufruf(f"/api/touren/{d['id']}", methode="DELETE", cookie=cookie)


def t_rdf():
    d = plan(params={"start": "Mainz", "ziel": "Bingen", "zielgruppe": "normal", "fahrrad": "normal", "bestaetigt": True})
    code, r, _ = aufruf("/api/rdf", {"plan": d, "variante": 0, "format": "turtle"})
    assert code == 200 and "rtf:Tour" in r.get("daten", ""), r
    code, q, _ = aufruf("/api/sparql", {"plan": d, "variante": 0, "abfrage": "unterkuenfte"})
    assert code == 200 and "zeilen" in q, q


def t_shacl():
    # Wünsche als SHACL-Regeln: 3 Tage und Campingplatz müssen erfüllt sein; zu kurze Wunschetappen werden erkannt
    d = plan(params={"start": "Mainz", "ziel": "Koblenz", "tage": 3, "unterkunft_typ": ["camp_site"],
                     "zielgruppe": "normal", "fahrrad": "normal", "bestaetigt": True})
    hat_route(d)
    code, j, _ = aufruf("/api/pruefen", {"plan": d, "variante": 0})
    assert code == 200, j
    st = {r["id"]: r["status"] for r in j["regeln"]}
    assert st.get("tage") == "ok" and st.get("unterkunft_camp_site") == "ok", st
    assert st.get("herkunft") == "ok", "Ort ohne Quelle"
    code, j, _ = aufruf("/api/pruefen", {"plan": {**d, "params": {**d["params"], "km_pro_tag": 20}}, "variante": 0})
    km = next(r for r in j["regeln"] if r["id"] == "km_pro_tag")
    assert km["status"] == "verletzt" and km["details"], km
    # gewählter Campingplatz als Übernachtung (wie „Hier übernachten“): Unterkunftsart darf nicht verloren gehen
    s1 = d["alternativen"][0]["etappen"][0]
    u = next(x for x in s1["unterkuenfte"] if x.get("typ") == "camp_site")
    felder = ("kat", "name", "lon", "lat", "detail", "ort", "adresse", "web", "quelle")
    nacht = {**{k: u[k] for k in felder if k in u}, "art": u["typ"], "typ": "nacht"}
    d2 = plan(params={**d["params"], "nur_variante": 0, "bestaetigt": True, "uebernachtungen": [nacht],
                      "wegpunkte": [{"typ": "nacht", "name": nacht["name"]}]})
    hat_route(d2)
    code, j, _ = aufruf("/api/pruefen", {"plan": d2, "variante": 0})
    st = {r["id"]: (r["status"], r["details"]) for r in j["regeln"]}
    assert st["unterkunft_camp_site"][0] == "ok", st["unterkunft_camp_site"]


def t_fotos():
    # Straßenfotos (Mapillary) auf dem Track – nur wenn ein Token eingerichtet ist
    code, cfg, _ = aufruf("/api/config")
    if not cfg.get("strassenfotos"):
        print("   (übersprungen: kein MAPILLARY_TOKEN)")
        return
    d = plan(params={"start": "Mainz", "ziel": "Koblenz", "tage": 2, "zielgruppe": "normal", "fahrrad": "normal", "bestaetigt": True})
    code, j, _ = aufruf("/api/fotos", {"geometrie": d["alternativen"][0]["geometrie"], "anzahl": 6})
    assert code == 200 and len(j["fotos"]) >= 3, j
    assert all(0 <= f["km"] <= d["alternativen"][0]["laenge_km"] + 1 for f in j["fotos"])


FAELLE = [("Status", t_health), ("Planung mit Parametern", t_normal), ("Planung aus Text", t_text),
          ("Rückfrage bei Widerspruch", t_rueckfrage_tage), ("Ziel außerhalb", t_ausserhalb),
          ("Großstadt vor gleichnamigem Dorf", t_grossstadt_vor_dorf), ("Radfernweg", t_radweg), ("Radfernweg ohne Ziel", t_radweg_ohne_ziel),
          ("Vorlieben", t_vorlieben), ("Rundtour", t_rundtour), ("Wettersuche", t_wetter),
          ("Wunsch-Stopp + nur gewählte Variante", t_poi_auswahl_und_via), ("Übernachtung", t_uebernachtung),
          ("Änderung per Chat", t_aenderung), ("Konto", t_konto), ("Linked Data (RDF/SPARQL)", t_rdf), ("SHACL-Prüfung der Wünsche", t_shacl),
          ("Straßenfotos", t_fotos)]

if __name__ == "__main__":
    schnell = "schnell" in sys.argv
    for name, f in FAELLE:
        if schnell and f in (t_text, t_rueckfrage_tage, t_ausserhalb, t_aenderung):
            continue
        fall(name, f)
    ok = sum(1 for e in ERGEBNISSE if e[0])
    print(f"\n{ok}/{len(ERGEBNISSE)} bestanden")
    sys.exit(0 if ok == len(ERGEBNISSE) else 1)
