"""Prüfung der Tour mit SHACL: Die Wünsche aus der Anfrage werden zu Regeln, die gegen den RDF-Graphen geprüft werden.

Ablauf:  Anfrage -> (LLM) Parameter -> Regeln (SHACL-Shapes, hier erzeugt)
         Planung -> RDF-Graph (linked_data.plan_graph)  ->  pySHACL validiert  ->  "erfüllt 5 von 6 Wünschen".
Damit prüft die Ontologie das Ergebnis, statt es nur zu exportieren: Was das Sprachmodell verstanden hat, wird
unabhängig vom Planungscode am Ergebnis nachgewiesen (oder eben nicht).

Jede Regel ist eine sh:NodeShape mit eigener IRI (regel:<id>) und Beschreibung (rdfs:label); verletzte Regeln
werden aus dem Validierungsbericht über sh:sourceShape zugeordnet.
"""
import time

from pyshacl import validate
from rdflib import RDF, RDFS, Graph, Namespace
from rdflib.namespace import SH

import linked_data
from plausibel import TAGES_KM, TAGES_KM_RAD

REGEL = Namespace("https://w3id.org/routify/regel/")
RTF, SCHEMA = linked_data.RTF, linked_data.SCHEMA

TOLERANZ = 1.10  # Etappenlänge: 10 % über dem Wunsch gilt noch als erfüllt
UNTERKUNFT_KLASSE = {"camp_site": ("Campingplatz", SCHEMA.Campground), "hotel": ("Hotel", SCHEMA.Hotel),
                     "guest_house": ("Pension", SCHEMA.BedAndBreakfast), "hostel": ("Hostel", SCHEMA.Hostel)}
STOPP_NAME = {"fahrradladen": "Fahrradwerkstatt", "verleih": "Fahrradverleih"}
PREFIXE = """@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> . @prefix rtf: <https://w3id.org/routify/ontologie#> .
@prefix gdi: <https://registry.gdi-de.org/up3/ontology/> . @prefix schema: <https://schema.org/> .
@prefix prov: <http://www.w3.org/ns/prov#> . @prefix regel: <https://w3id.org/routify/regel/> .
"""


def _shape(rid, label, art, ziel, koerper, schwere="Violation"):
    """Eine Regel als Turtle-Text. art: "wunsch" (aus der Anfrage) oder "standard" (gilt immer)."""
    return f"""
regel:{rid} a sh:NodeShape ; rdfs:label "{label}"@de ; rtf:regelArt "{art}" ;
    sh:severity sh:{schwere} ; {ziel} ;
    {koerper} .
"""


def regeln(params):
    """SHACL-Shapes (Turtle) aus den erkannten Parametern. Rückgabe: (turtle, {id: Zusatzinfo für Meldungen})."""
    p = params or {}
    teile, info = [], {}

    # ---- Wünsche aus der Anfrage
    tage = p.get("tage")
    if tage and not p.get("rundtour"):
        teile.append(_shape("tage", f"{tage} {'Tag' if tage == 1 else 'Tage'}", "wunsch", "sh:targetClass rtf:Tour",
                            f"sh:property [ sh:path rtf:hatEtappe ; sh:minCount {tage} ; sh:maxCount {tage} ]"))
    kpt = p.get("km_pro_tag")
    if kpt and not p.get("rundtour"):
        info["km_pro_tag"] = kpt
        teile.append(_shape("km_pro_tag", f"höchstens ca. {kpt} km pro Tag", "wunsch", "sh:targetClass rtf:Etappe",
                            f"sh:property [ sh:path gdi:laenge ; sh:maxInclusive {int(kpt * 1000 * TOLERANZ)} ]"))
    for typ in p.get("unterkunft_typ") or []:
        if typ in UNTERKUNFT_KLASSE:
            name, klasse = UNTERKUNFT_KLASSE[typ]
            teile.append(_shape(f"unterkunft_{typ}", f"{name} zum Übernachten", "wunsch",
                                "sh:targetClass rtf:EtappeMitUebernachtung",
                                f"""sh:or ( [ sh:path rtf:uebernachtungIn ; sh:qualifiedValueShape [ sh:class <{klasse}> ] ; sh:qualifiedMinCount 1 ]
                                            [ sh:path rtf:unterkunftsvorschlag ; sh:qualifiedValueShape [ sh:class <{klasse}> ] ; sh:qualifiedMinCount 1 ] )"""))
    for w in p.get("poi_wuensche") or []:
        kat = w.get("kategorie")
        if kat in linked_data.KLASSE_HALT:
            klasse = linked_data.KLASSE_HALT[kat]
            teile.append(_shape(f"stopp_{kat}", f"Stopp: {w.get('name') or STOPP_NAME.get(kat, kat)}", "wunsch",
                                "sh:targetClass rtf:Tour",
                                f"sh:property [ sh:path rtf:fuehrtUeber ; sh:qualifiedValueShape [ sh:class <{klasse}> ] ; sh:qualifiedMinCount 1 ]",
                                "Warning"))  # offen, bis ein Vorschlag gewählt ist
    if p.get("radweg"):
        teile.append(_shape("radweg", f"auf dem {p['radweg']}", "wunsch", "sh:targetClass rtf:Tour",
                            "sh:property [ sh:path rtf:folgtRadweg ; sh:minCount 1 ]"))
    vorl = set(p.get("vorlieben") or [])
    if "flach" in vorl:
        teile.append(_shape("flach", "möglichst flach (Steigung höchstens 6 %)", "wunsch", "sh:targetClass rtf:Etappe",
                            "sh:property [ sh:path rtf:maxSteigung ; sh:maxInclusive 6.0 ]", "Warning"))
    if "asphalt" in vorl:
        teile.append(_shape("asphalt", "asphaltiert (mind. 80 % Asphalt)", "wunsch", "sh:targetClass rtf:Etappe",
                            "sh:property [ sh:path rtf:anteilAsphalt ; sh:minInclusive 0.8 ]", "Warning"))
    if "ruhig" in vorl:
        teile.append(_shape("ruhig", "wenig Verkehr (höchstens 10 % Hauptstraße)", "wunsch", "sh:targetClass rtf:Etappe",
                            "sh:property [ sh:path rtf:anteilHauptstrasse ; sh:maxInclusive 0.1 ]", "Warning"))
    ws = p.get("wetter_suche") or {}
    if ws.get("kriterium") in ("trocken", "rueckenwind"):
        teile.append(_shape("trocken", "trocken (höchstens 0,5 mm Regen je Tag)", "wunsch", "sh:targetClass rtf:Etappe",
                            "sh:property [ sh:path ( rtf:hatWetter rtf:regenMm ) ; sh:maxInclusive 0.5 ]", "Warning"))
    gruppe = p.get("zielgruppe")
    if gruppe in ("familie", "senioren") and not p.get("km_pro_tag"):
        grenze = TAGES_KM[gruppe][1]
        info["zumutbar"] = grenze
        name = "Familie" if gruppe == "familie" else "Senioren"
        teile.append(_shape("zumutbar", f"{name}: Etappe höchstens {grenze} km, Steigung höchstens 8 %", "wunsch",
                            "sh:targetClass rtf:Etappe",
                            f"sh:property [ sh:path gdi:laenge ; sh:maxInclusive {grenze * 1000} ] ; "
                            "sh:property [ sh:path rtf:maxSteigung ; sh:maxInclusive 8.0 ]", "Warning"))
    elif p.get("fahrrad") in TAGES_KM_RAD and not p.get("km_pro_tag"):
        pass  # sportliche Räder: keine Obergrenze vorgeben

    # ---- Grundregeln (gelten für jede Tour)
    teile.append(_shape("notausstieg", "Bahnhof als Notausstieg (≤ 5 km) auf jeder Etappe", "standard",
                        "sh:targetClass rtf:Etappe",
                        "sh:property [ sh:path rtf:notausstieg ; sh:qualifiedValueShape [ sh:property [ sh:path rtf:abstandKm ; sh:maxInclusive 5.0 ] ] ; sh:qualifiedMinCount 1 ]",
                        "Warning"))
    teile.append(_shape("herkunft", "jede Ortsangabe mit Quelle (Datensatz und Lizenz)", "standard",
                        "sh:targetClass rtf:Ort", "sh:property [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ]"))
    return PREFIXE + "".join(teile), info


def _tag(g, fokus):
    n = g.value(fokus, RTF.tagNummer)
    return int(n) if n is not None else None


def _detail(rid, g, fokus, wert, info):
    """Verständliche Meldung zu einem Verstoß."""
    tag = _tag(g, fokus)
    vor = f"Tag {tag}: " if tag else ""
    w = float(wert) if wert is not None and str(wert).replace(".", "", 1).isdigit() else None
    if rid == "km_pro_tag" and w is not None:
        return f"{vor}{w / 1000:.0f} km (Wunsch ≤ {info['km_pro_tag']} km)"
    if rid == "zumutbar" and w is not None:
        return f"{vor}{w / 1000:.0f} km" if w > 100 else f"{vor}Steigung bis {w:.1f} %".replace(".", ",")
    if rid == "flach" and w is not None:
        return f"{vor}Steigung bis {w:.1f} %".replace(".", ",")
    if rid in ("asphalt", "ruhig") and w is not None:
        return f"{vor}{w * 100:.0f} % {'Asphalt' if rid == 'asphalt' else 'Hauptstraße'}"
    if rid == "trocken" and w is not None:
        return f"{vor}{w:.1f} mm Regen".replace(".", ",")
    if rid == "tage":
        return f"{len(list(g.objects(fokus, RTF.hatEtappe)))} Etappen geplant"
    if rid.startswith("stopp_"):
        return "noch nicht in die Route übernommen – Vorschlag in der Planung wählen"
    if rid.startswith("unterkunft_"):
        return f"{vor}keine Unterkunft dieser Art in der Nähe gefunden"
    if rid == "notausstieg":
        return f"{vor}kein Bahnhof im Umkreis von 5 km"
    if rid == "radweg":
        return "Route folgt nicht dem Radweg (Verlauf nicht gefunden)"
    if rid == "herkunft":
        name = g.value(fokus, SCHEMA.name)
        return f"ohne Quelle: {name or fokus}"
    return vor + (str(wert) if wert is not None else "nicht erfüllt")


def pruefen(plan, variante=0, anfrage_text=None):
    """Prüft eine Variante. Rückgabe: Regeln mit Status und Details, Zusammenfassung, Shapes als Turtle."""
    t0 = time.time()
    daten = linked_data.plan_graph(plan, variante, anfrage_text)
    turtle, info = regeln(plan.get("params"))
    shapes = Graph().parse(data=turtle, format="turtle")
    # Ontologie mitgeben, damit Unterklassen zählen (z. B. rtf:EtappeMitUebernachtung ⊑ rtf:Etappe)
    konform, bericht, _ = validate(daten, shacl_graph=shapes, ont_graph=linked_data.TBOX, inference="rdfs",
                                   allow_warnings=True, advanced=True)
    eltern = {}  # Property-Shape -> Regel
    for regel in shapes.subjects(RDF.type, SH.NodeShape):
        eltern[regel] = regel
        for ps in shapes.objects(regel, SH.property):
            eltern[ps] = regel
    verstoesse = {}
    for r in bericht.subjects(RDF.type, SH.ValidationResult):
        quelle = bericht.value(r, SH.sourceShape)
        regel = eltern.get(quelle, quelle)
        verstoesse.setdefault(regel, []).append((bericht.value(r, SH.focusNode), bericht.value(r, SH.value)))
    ergebnis = []
    for regel in shapes.subjects(RDF.type, SH.NodeShape):
        rid = str(regel).replace(str(REGEL), "")
        fehler = verstoesse.get(regel, [])
        details = sorted({_detail(rid, daten, f, w, info) for f, w in fehler})
        schwere = shapes.value(regel, SH.severity)
        ergebnis.append({"id": rid, "regel": str(shapes.value(regel, RDFS.label)),
                         "art": str(shapes.value(regel, RTF.regelArt)),
                         "status": "ok" if not fehler else ("warnung" if schwere == SH.Warning else "verletzt"),
                         "details": details[:6] + ([f"… {len(details) - 6} weitere"] if len(details) > 6 else [])})
    reihen = {"wunsch": 0, "standard": 1}
    ergebnis.sort(key=lambda e: (reihen.get(e["art"], 2), e["status"] == "ok", e["regel"]))
    wuensche = [e for e in ergebnis if e["art"] == "wunsch"]
    return {"regeln": ergebnis, "wuensche_gesamt": len(wuensche),
            "wuensche_erfuellt": sum(e["status"] == "ok" for e in wuensche),
            "standard_erfuellt": sum(e["status"] == "ok" for e in ergebnis if e["art"] == "standard"),
            "standard_gesamt": sum(e["art"] == "standard" for e in ergebnis),
            "konform": bool(konform), "tripel": len(daten), "sekunden": round(time.time() - t0, 2),
            "shacl": turtle.strip()}
