"""Linked Data: eine Planung als RDF-Graph nach der Routify-Ontologie (code/ontologie/routify.ttl).

- Tour/Etappen/Etappenpunkte als Unterklassen der GDI-DE-Radnetz-Ontologie (TouristenRoute, Streckenabschnitt, Knoten)
- Orte unterwegs mit schema.org-Klassen, GeoSPARQL-Geometrie, Wikidata-Verknüpfung (owl:sameAs)
- Herkunft jedes Objekts (prov:wasDerivedFrom -> Datensatz mit Lizenz) und die Anfrage, aus der die Tour entstand

Damit ist jede Angabe der App nachprüfbar: Woher kommt sie, und was hat das Sprachmodell verstanden?
"""
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD
import rdflib.plugins.sparql

# Sicherheit: SPARQL darf keine Graphen nachladen (FROM <file:///…> bzw. fremde Adressen) und nicht nach außen fragen (SERVICE)
rdflib.plugins.sparql.SPARQL_LOAD_GRAPHS = False

from daten import WD_GEMEINDEN, gemeinde_von

ONTO_DATEI = Path(__file__).resolve().parents[1] / "ontologie" / "routify.ttl"
RTF = Namespace("https://w3id.org/routify/ontologie#")
TOUR = Namespace("https://w3id.org/routify/tour/")
GDI = Namespace("https://registry.gdi-de.org/up3/ontology/")
SCHEMA = Namespace("https://schema.org/")
GSP = Namespace("http://www.opengis.net/ont/geosparql#")
PROV = Namespace("http://www.w3.org/ns/prov#")
WD = Namespace("http://www.wikidata.org/entity/")

TBOX = Graph()
TBOX.parse(ONTO_DATEI)

KLASSE_HALT = {"fahrradladen": RTF.Fahrradservice, "verleih": RTF.Fahrradservice}


def _datensaetze(quelle):
    q = (quelle or "").lower()
    out = []
    if "openstreetmap" in q or "osm" in q:
        out.append(RTF.ds_osm)
    if "poi-open" in q:
        out.append(RTF.ds_poi_open)
    return out


def _id(*teile):
    return hashlib.sha1("|".join(str(t) for t in teile).encode()).hexdigest()[:12]


def _wkt_punkt(lon, lat):
    return Literal(f"POINT({lon:.6f} {lat:.6f})", datatype=GSP.wktLiteral)


def plan_graph(plan, variante=0, anfrage_text=None):
    """RDF-Graph einer Planung. `plan` ist die Antwort von /api/plan (oder ein Auszug mit params, orte, alternativen)."""
    g = Graph()
    for p, ns in (("rtf", RTF), ("tour", TOUR), ("gdi", GDI), ("schema", SCHEMA), ("gsp", GSP), ("prov", PROV),
                  ("dct", DCTERMS), ("owl", OWL), ("wd", WD), ("xsd", XSD)):
        g.bind(p, ns)
    # Datensatz-Beschreibungen (Titel, Lizenz) mitliefern
    for s in TBOX.subjects(RDF.type, RTF.Datensatz):
        for t in TBOX.triples((s, None, None)):
            g.add(t)

    params = plan.get("params") or {}
    alt = (plan.get("alternativen") or [])[variante]
    orte = plan.get("orte") or []
    tid = _id(params.get("start"), params.get("ziel"), alt.get("laenge_km"), plan.get("startdatum"))
    tour = TOUR[tid]
    titel = f"{orte[0]['label'] if orte else params.get('start')} → {orte[-1]['label'] if orte else params.get('ziel')}"

    g.add((tour, RDF.type, RTF.Tour))
    g.add((tour, RDF.type, GDI.TouristenRoute))
    g.add((tour, GDI.name, Literal(titel, datatype=XSD.string)))  # gdi:name hat range xsd:string
    g.add((tour, GDI.istTouristisch, Literal(True)))
    # gdi:laenge/gdi:steigung haben domain gdi:Streckenabschnitt -> an der Tour eigene Eigenschaften (sonst würde die Tour zum Abschnitt)
    g.add((tour, RTF.gesamtlaenge, Literal(int(round(alt["laenge_km"] * 1000)), datatype=XSD.integer)))
    g.add((tour, RTF.anstiegHm, Literal(int(alt.get("anstieg_m") or 0), datatype=XSD.integer)))
    if alt.get("max_steigung") is not None:
        g.add((tour, RTF.maxSteigung, Literal(float(alt["max_steigung"]), datatype=XSD.double)))
    g.add((tour, RTF.routingProfil, Literal(alt.get("profil"))))
    g.add((tour, RTF.zielgruppe, Literal(params.get("zielgruppe") or "normal")))
    linie = alt.get("geometrie") or []
    if linie:
        schritt = max(1, len(linie) // 400)
        pts = linie[::schritt] + [linie[-1]]
        geom = BNode()
        g.add((tour, GSP.hasGeometry, geom))
        g.add((geom, RDF.type, GSP.Geometry))
        g.add((geom, GSP.asWKT, Literal("LINESTRING(" + ", ".join(f"{lo:.5f} {la:.5f}" for la, lo in pts) + ")",
                                        datatype=GSP.wktLiteral)))
    # Herkunft der Tour selbst
    g.add((tour, PROV.wasDerivedFrom, RTF.ds_brouter))
    # Anfrage -> Parameter (was hat das Sprachmodell verstanden?)
    anfrage = TOUR[tid + "_anfrage"]
    g.add((anfrage, RDF.type, RTF.Anfrage))
    if anfrage_text:
        g.add((anfrage, RTF.anfrageText, Literal(anfrage_text, lang="de")))
    sichtbar = {k: v for k, v in params.items() if v not in (None, [], "", False) and k not in ("bestaetigt",)}
    g.add((anfrage, RTF.parameter, Literal(json.dumps(sichtbar, ensure_ascii=False))))
    g.add((tour, PROV.wasGeneratedBy, anfrage))
    if plan.get("radweg"):
        rw = TOUR["radweg_" + re.sub(r"[^a-z0-9]", "", plan["radweg"]["name"].lower())]
        g.add((rw, RDF.type, GDI.Route))
        g.add((rw, GDI.name, Literal(plan["radweg"]["name"], datatype=XSD.string)))
        g.add((rw, PROV.wasDerivedFrom, RTF.ds_osm))
        g.add((tour, RTF.folgtRadweg, rw))

    def gemeinde(info):
        """Gemeinde als gdi:Gemeinde mit amtlichem Schlüssel und Wikidata-Verknüpfung."""
        if not info or not info.get("ags"):
            return None
        u = TOUR["gemeinde_" + info["ags"]]
        g.add((u, RDF.type, GDI.Gemeinde))
        g.add((u, SCHEMA.name, Literal(info["name"])))
        if info.get("ars"):
            g.add((u, GDI.schluessel, Literal(info["ars"])))
        qid = info.get("wikidata") or WD_GEMEINDEN.get(info["ags"], {}).get("qid")
        if qid:
            g.add((u, OWL.sameAs, WD[qid]))
        g.add((u, PROV.wasDerivedFrom, RTF.ds_poi_open))
        return u

    def ort(it, klassen, routen_km=None, abstand=None):
        """Ort als Ressource: Klasse(n), Name, Geometrie, Herkunft, Wikidata/OSM-Verknüpfung."""
        key = it.get("osm") or it.get("id") or _id(it.get("name"), round(it["lon"], 5), round(it["lat"], 5))
        u = TOUR["ort_" + _id(key)]
        for k in klassen:
            g.add((u, RDF.type, k))
        g.add((u, RDF.type, RTF.Ort))
        if it.get("name"):
            g.add((u, SCHEMA.name, Literal(it["name"])))
        geom = BNode()
        g.add((u, GSP.hasGeometry, geom))
        g.add((geom, GSP.asWKT, _wkt_punkt(it["lon"], it["lat"])))
        for ds in _datensaetze(it.get("quelle")):
            g.add((u, PROV.wasDerivedFrom, ds))
        if it.get("wikidata"):
            g.add((u, OWL.sameAs, WD[str(it["wikidata"]).strip()]))
        if it.get("osm"):
            g.add((u, RDFS.seeAlso, URIRef("https://www.openstreetmap.org/" + it["osm"])))
        if it.get("web") and str(it["web"]).startswith("http"):
            g.add((u, SCHEMA.url, URIRef(str(it["web"]).split()[0])))
        if it.get("ort"):
            g.add((u, SCHEMA.addressLocality, Literal(it["ort"])))
        if it.get("adresse"):
            g.add((u, SCHEMA.address, Literal(it["adresse"])))
        if it.get("telefon"):
            g.add((u, SCHEMA.telephone, Literal(it["telefon"])))
        if routen_km is not None or abstand is not None:
            g.add((u, RTF.liegtAn, tour))
        if routen_km is not None:
            g.add((u, RTF.routenKm, Literal(float(routen_km), datatype=XSD.decimal)))
        if abstand is not None:
            g.add((u, RTF.abstandKm, Literal(float(abstand), datatype=XSD.decimal)))
        return u

    def unterkunft_klassen(u):
        art = u.get("art") or u.get("typ")  # gewählte Übernachtung: typ = "nacht" (Wegpunkt-Rolle), art = Unterkunftsart
        k = [RTF.Unterkunft, SCHEMA.LodgingBusiness]
        for a in u.get("typen") or [art]:
            if a == "camp_site":
                k += [RTF.Campingplatz, SCHEMA.Campground]
            k += {"hotel": [SCHEMA.Hotel], "motel": [SCHEMA.Motel], "hostel": [SCHEMA.Hostel],
                  "guest_house": [SCHEMA.BedAndBreakfast], "apartment": [SCHEMA.VacationRental]}.get(a, [])
        return list(dict.fromkeys(k))

    # Etappen
    start_tag = date.fromisoformat(plan["startdatum"]) if plan.get("startdatum") else None
    punkt_vorher = None
    if orte:
        punkt_vorher = TOUR[tid + "_start"]
        g.add((punkt_vorher, RDF.type, RTF.Etappenpunkt))
        g.add((punkt_vorher, SCHEMA.name, Literal(orte[0]["label"])))
        geom = BNode(); g.add((punkt_vorher, GSP.hasGeometry, geom)); g.add((geom, GSP.asWKT, _wkt_punkt(orte[0]["lon"], orte[0]["lat"])))
        gu = gemeinde(gemeinde_von(orte[0]["lon"], orte[0]["lat"]))
        if gu is not None:
            g.add((punkt_vorher, GDI.befindetIn, gu))
    for s in alt.get("etappen") or []:
        e = TOUR[f"{tid}_etappe{s['nr']}"]
        g.add((tour, RTF.hatEtappe, e))
        g.add((e, RDF.type, RTF.Etappe))
        g.add((e, RDF.type, GDI.Streckenabschnitt))
        if not s.get("letzte"):
            g.add((e, RDF.type, RTF.EtappeMitUebernachtung))
        g.add((e, RTF.tagNummer, Literal(s["nr"], datatype=XSD.integer)))
        if start_tag:
            g.add((e, RTF.datum, Literal((start_tag + timedelta(days=s["nr"] - 1)).isoformat(), datatype=XSD.date)))
        g.add((e, GDI.laenge, Literal(int(round(s["laenge_km"] * 1000)), datatype=XSD.integer)))
        if s.get("anstieg_m") is not None:
            g.add((e, RTF.anstiegHm, Literal(int(s["anstieg_m"]), datatype=XSD.integer)))
        if s.get("max_steigung") is not None:
            g.add((e, RTF.maxSteigung, Literal(float(s["max_steigung"]), datatype=XSD.double)))  # gdi:steigung = Längsneigung, nicht Maximum
        if s.get("fahrzeit_h") is not None:
            g.add((e, RTF.fahrzeitStunden, Literal(float(s["fahrzeit_h"]), datatype=XSD.decimal)))
        wg = s.get("wege") or {}
        for feld, prop, kat in (("wegtyp", RTF.anteilRadweg, "radweg"), ("untergrund", RTF.anteilAsphalt, "asphalt"),
                                ("wegtyp", RTF.anteilHauptstrasse, "hauptstrasse")):
            summe = sum((wg.get(feld) or {}).values()) or 0
            if summe:
                g.add((e, prop, Literal(round((wg[feld].get(kat) or 0) / summe, 3), datatype=XSD.decimal)))
        ende = TOUR[f"{tid}_ende{s['nr']}"]
        g.add((ende, RDF.type, RTF.Etappenpunkt))
        geom = BNode(); g.add((ende, GSP.hasGeometry, geom)); g.add((geom, GSP.asWKT, _wkt_punkt(s["ende"]["lon"], s["ende"]["lat"])))
        g.add((ende, SCHEMA.name, Literal("Ziel" if s.get("letzte") else f"Ende Tag {s['nr']}", lang="de")))
        gu = gemeinde(gemeinde_von(s["ende"]["lon"], s["ende"]["lat"]))
        if gu is not None:
            g.add((ende, GDI.befindetIn, gu))
        if punkt_vorher is not None:
            g.add((e, GDI.beginntBeiKnoten, punkt_vorher))
        g.add((e, GDI.endetBeiKnoten, ende))
        punkt_vorher = ende
        if s.get("uebernachtung"):
            g.add((e, RTF.uebernachtungIn, ort(s["uebernachtung"], unterkunft_klassen(s["uebernachtung"]))))
        for u in s.get("unterkuenfte") or []:
            if not s.get("uebernachtung"):
                g.add((e, RTF.unterkunftsvorschlag, ort(u, unterkunft_klassen(u), abstand=u.get("dist_km"))))
        for b in s.get("notausstiege") or []:
            bu = ort({**b, "id": b.get("id")}, [RTF.Bahnhof, SCHEMA.TrainStation],
                     routen_km=b.get("route_km"), abstand=b.get("dist_km"))
            g.add((e, RTF.notausstieg, bu))
            gu = gemeinde({"name": b.get("gemeinde"), "ags": b.get("ags"), "ars": b.get("ars"),
                           "wikidata": b.get("gemeinde_wikidata")})
            if gu is not None:
                g.add((bu, GDI.befindetIn, gu))
        w = s.get("wetter") or {}
        if w and not w.get("hinweis"):
            wl = TOUR[f"{tid}_wetter{s['nr']}"]
            g.add((e, RTF.hatWetter, wl))
            g.add((wl, RDF.type, RTF.Wetterlage))
            g.add((wl, PROV.wasDerivedFrom, RTF.ds_dwd))
            for k, prop in (("regen_mm", RTF.regenMm), ("t_max", RTF.tMaxC), ("wind_kmh", RTF.windKmh),
                            ("wind_richtung", RTF.windRichtungGrad)):
                if w.get(k) is not None:
                    g.add((wl, prop, Literal(float(w[k]), datatype=XSD.decimal)))
    # Halte, über die die Tour führt
    for w in plan.get("wegpunkte_aktuell") or alt.get("wegpunkte") or plan.get("wegpunkte") or []:
        kl = [RTF.Halt] + ([KLASSE_HALT[w["kat"]]] if w.get("kat") in KLASSE_HALT else [])
        if w.get("typ") == "nacht":
            kl = unterkunft_klassen(w)
        g.add((tour, RTF.fuehrtUeber, ort(w, kl)))
    # Fahrrad-Service und Vorschläge entlang der Route
    for q in alt.get("rad_pois") or []:
        ort(q, [RTF.Fahrradservice, SCHEMA.LocalBusiness], routen_km=q.get("route_km"))
    for grp in plan.get("poi_auswahl") or []:
        for q in grp.get("kandidaten") or []:
            ort(q, [RTF.Halt, KLASSE_HALT.get(grp["kategorie"], RTF.Halt)], routen_km=q.get("route_km"), abstand=q.get("dist_km"))
    return g


# ----------------------------------------------------------------------------- Beispielabfragen (SPARQL)

PREFIXE = """PREFIX rtf: <https://w3id.org/routify/ontologie#>
PREFIX gdi: <https://registry.gdi-de.org/up3/ontology/>
PREFIX schema: <https://schema.org/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
"""

ABFRAGEN = {
    "etappen": ("Etappen mit Länge, Steigung und Radweganteil", """
SELECT ?tag ?datum (?laenge / 1000 AS ?km) ?hm ?maxSteigung ?radwegAnteil WHERE {
  ?tour rtf:hatEtappe ?e .
  ?e rtf:tagNummer ?tag ; gdi:laenge ?laenge .
  OPTIONAL { ?e rtf:datum ?datum } OPTIONAL { ?e rtf:anstiegHm ?hm }
  OPTIONAL { ?e rtf:maxSteigung ?maxSteigung } OPTIONAL { ?e rtf:anteilRadweg ?radwegAnteil }
} ORDER BY ?tag"""),
    "unterkuenfte": ("Unterkünfte je Etappe", """
SELECT ?tag ?name ?abstandKm WHERE {
  ?e rtf:tagNummer ?tag .
  { ?e rtf:uebernachtungIn ?u } UNION { ?e rtf:unterkunftsvorschlag ?u }
  ?u a rtf:Unterkunft ; schema:name ?name .
  OPTIONAL { ?u rtf:abstandKm ?abstandKm }
} ORDER BY ?tag ?abstandKm"""),
    "quellen": ("Woher stammen die Daten dieser Tour?", """
SELECT ?datensatz ?titel (COUNT(DISTINCT ?o) AS ?objekte) WHERE {
  ?o prov:wasDerivedFrom ?datensatz .
  ?datensatz dct:title ?titel .
} GROUP BY ?datensatz ?titel ORDER BY DESC(?objekte)"""),
    "wikidata": ("Gemeinden entlang der Tour mit Wikidata (über amtlichen Gemeindeschlüssel)", """
SELECT DISTINCT ?gemeinde ?wikidata ?regionalschluessel WHERE {
  { ?punkt a rtf:Etappenpunkt } UNION { ?punkt a rtf:Bahnhof }
  ?punkt gdi:befindetIn ?g .
  ?g schema:name ?gemeinde ; owl:sameAs ?wikidata .
  OPTIONAL { ?g gdi:schluessel ?regionalschluessel }
} ORDER BY ?gemeinde"""),
    "notausstiege": ("Notausstiege (Bahnhöfe) je Etappe, nächstgelegene zuerst", """
SELECT ?tag ?bahnhof ?abstandKm ?routenKm WHERE {
  ?e rtf:tagNummer ?tag ; rtf:notausstieg ?b .
  ?b schema:name ?bahnhof ; rtf:abstandKm ?abstandKm ; rtf:routenKm ?routenKm .
} ORDER BY ?tag ?abstandKm LIMIT 40"""),
    "anfrage": ("Was hat das Sprachmodell verstanden?", """
SELECT ?text ?parameter WHERE {
  ?tour prov:wasGeneratedBy ?a .
  OPTIONAL { ?a rtf:anfrageText ?text }
  ?a rtf:parameter ?parameter .
}"""),
}


def abfragen_liste():
    return [{"id": k, "titel": t, "sparql": PREFIXE + q.strip()} for k, (t, q) in ABFRAGEN.items()]


def sparql(g, abfrage):
    """SPARQL-SELECT auf dem Graphen. `abfrage`: Schlüssel aus ABFRAGEN.
    Eigene Abfragen sind bewusst nicht erlaubt: Über FROM/SERVICE könnten sie Dateien des Rechners oder andere
    Adressen abfragen, sobald die App im Netz geteilt wird."""
    if abfrage not in ABFRAGEN:
        raise ValueError("Unbekannte Abfrage. Erlaubt: " + ", ".join(ABFRAGEN))
    text = PREFIXE + ABFRAGEN[abfrage][1]
    erg = g.query(text)
    kopf = [str(v) for v in erg.vars]
    zeilen = [[(str(x) if x is not None else "") for x in row] for row in erg]
    return {"kopf": kopf, "zeilen": zeilen, "sparql": text.strip()}


def serialisieren(g, format="turtle"):
    return g.serialize(format="json-ld" if format in ("jsonld", "json-ld") else "turtle")
