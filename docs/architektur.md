# Architektur – Routify

## Überblick

```
Browser (http://localhost:8000)
  index.html + static/css + static/js       Chat | Aktuelle Planung | Karte (Leaflet)
        │  POST /api/plan  (Text oder Parameter, vorherige Planung als Kontext)
        ▼
Backend FastAPI (code/backend)
  1. verstehen.py   Text → Parameter: Ollama qwen3:8b mit JSON-Schema (bis 6 Anfragen parallel), dann Regeln gegen den Originaltext
  2. ortssuche.py   Ortsnamen → Koordinaten (Photon, Cache, Offline-Ortsverzeichnis)
  3. plausibel.py   Rückfragen: zu weit/zu kurz pro Tag, außerhalb DE, Tage ≠ km/Tag
  4. routing.py     BRouter: 2 Varianten (Hauptroute + Alternative; Profil + Vorlieben als Profilparameter), Korridore, Radfernweg, Rundtour
  5. analyse.py     Etappen, Unterkünfte, Höhen (hoehen.py), Wege & Untergrund, Stopps,
                    Notausstiege, Fahrzeit
  6. wetter.py      DWD/Bright Sky je Etappe, Wind relativ zur Fahrtrichtung, Suche nach dem besten Tag
        │
        ├─ POST /api/rdf, /api/sparql   linked_data.py: Planung → RDF-Graph (Routify-Ontologie) → Turtle/JSON-LD, SPARQL
        ├─ POST /api/pruefen            pruefung.py: Wünsche → SHACL-Regeln → pySHACL gegen den Graphen („3 von 4 erfüllt“)
        ├─ POST /api/sprache            sprache.py: Audio → Text, lokal mit Whisper (faster-whisper small)
        ├─ POST /api/fotos, /api/foto   strassenfotos.py: Mapillary-Fotos auf dem Track (erst beim Aufklappen)
        └─ /api/konto/*                 konto.py: SQLite data/routify.db

Teilen im lokalen Netz: ./start.sh teilen → /teilen (QR-Code) → Handys über https://<Netzadresse>:8443
(code/scripts/https_tor.py, selbst ausgestelltes Zertifikat, reicht an Port 8000 weiter)
```

Grundsatz: **Das LLM übersetzt, der Code plant, die Geodaten entscheiden.** Das LLM liefert nie Koordinaten oder Routen.

## Backend-Module (`code/backend/`)

| Modul | Aufgabe |
|---|---|
| `app.py` | FastAPI-App: Endpunkte, Start (LLM aufwärmen), Fehlerhandler (immer JSON), statische Dateien |
| `planung.py` | Ablauf von `/api/plan` (Schritte 1–6 oben), Zeitmessung je Schritt |
| `konfig.py` | Pfade, `.env` (leere Werte werden übersprungen), Dienst-URLs |
| `daten.py` | lädt `data/prepared/*` in den Speicher, räumliche Indizes, POI-Kategorien, Gemeinde (AGS/Wikidata) zu einem Punkt |
| `geo.py` | Entfernung, Raster-Index, Peilung, Wind relativ zur Fahrtrichtung |
| `verstehen.py` | LLM-Aufruf, Parameterschema, Wortlisten (Tage, Wunsch-Stopps, Vorlieben, Wetter, Bahn, Rundtour), Plausibilisierung, Änderungen |
| `ortssuche.py` | Photon mit Orts-Filtern, Nähe zum Start, exakter Name, Cache, Offline-Rückfall |
| `plausibel.py` | Tages-km je Zielgruppe/Rad, Rückfragen mit Optionen, Ort bei einem Punkt |
| `routing.py` | BRouter-Aufrufe (max. 3 parallel), Profilwahl, Vorlieben → Profilvariablen, Korridore, Radfernweg-Variante, Rundtouren |
| `radwege.py` | Index der OSM-Radrouten, Verlauf per Overpass (Cache), Wegenetz + Dijkstra, Ziel entlang des Radwegs |
| `analyse.py` | Etappen, Unterkünfte, POIs entlang, Brücken/Tunnel, Höhen, Wegtyp/Untergrund, Wunsch-Stopps, Notausstiege, Fahrzeit |
| `hoehen.py` | Höhenprofil aus den BRouter-Höhen (SRTM) im 50-m-Raster, Brücken/Tunnel überbrücken, Höhenmeter und max. Steigung |
| `wetter.py` | Bright-Sky-Abfrage, Tagesbewertung (trocken / gut / Rückenwind), bester Starttag |
| `linked_data.py` | RDF-Graph je Planung, 6 SPARQL-Abfragen, Serialisierung |
| `konto.py` | Konten (scrypt), Sitzungen, Touren, Voreinstellungen, Verlauf |
| `pruefung.py` | SHACL-Prüfung: erzeugt aus den Parametern Regeln (Tage, km/Tag, Unterkunftsart, Stopps, Radweg, Vorlieben, Wetter, Zielgruppe) plus Grundregeln (Bahnhof ≤ 5 km, Herkunft) und validiert mit pySHACL (RDFS-Inferenz) |
| `strassenfotos.py` + `mvt.py` | Straßenfotos (Mapillary) auf dem Track: Abdeckungskacheln lesen, Foto ≤ 20 m von der Route in Fahrtrichtung wählen, Bilder über den Server ausliefern (`/api/fotos`, `/api/foto/{id}`) |
| `sprache.py` | Spracheingabe lokal: Whisper-Modell aus `data/whisper/small`, Transkription deutsch mit Fachbegriffs-Hinweis |

## Frontend (`code/frontend/`)

`index.html` enthält nur das Gerüst. Leaflet, Chart.js und der QR-Code-Generator liegen in `static/vendor/` (keine fremden CDNs). Die Skripte sind klassische Skripte mit gemeinsamen globalen Namen und werden in dieser Reihenfolge geladen:

| Datei | Aufgabe |
|---|---|
| `grundlagen.js` | Konstanten, Zustand (`data`, `current`), Helfer (`$`, `esc`, Fahrzeit) |
| `karte.js` | Leaflet-Karte, Hintergrundkarten, Ebenen und Kartenleiste, Höhenprofil (Chart.js) |
| `chat.js` | Chat, `send()` an `/api/plan`, Rückfragen, Änderungsanzeige, Hilfe „Was kann ich fragen?“ |
| `planung.js` | Spalte „Aktuelle Planung“: Kennzahlen, Varianten, Etappen, Wetter, Wege |
| `wegpunkte.js` | Wegpunkte-Liste, Übernachtung wählen, Etappen ein-/ausklappen |
| `export.js` | GPX-Export im Browser |
| `linkeddaten.js` | „Daten & Herkunft“ (Herkunft, SPARQL, Turtle/JSON-LD) und Prüfkarte „x von y Wünschen erfüllt“ (SHACL) |
| `fotos.js` | Karte „Straßenfotos“ (lädt erst beim Aufklappen), Galerie, Großansicht, Kamerasymbole auf der Karte |
| `einstellungen.js` | Formular „Einstellungen“ (ohne LLM neu planen) |
| `konto.js` | Anmeldung, Touren, Voreinstellungen, Verlauf |
| `start.js` | Eingabe, Spracheingabe (MediaRecorder → `/api/sprache`, Zwischenstand alle 2,5 s), „Neue Planung“, Demo-Links, Spalten einklappen |

Dazu `teilen.html`: QR-Code-Seite (`/teilen`) mit der Netzadresse, QR-Bibliothek `qrcode-generator` lokal in `static/vendor/`.

## Ontologie (`code/ontologie/routify.ttl`)

```
rtf:Tour        ⊑ gdi:TouristenRoute     gdi:name, rtf:gesamtlaenge (m), rtf:maxSteigung (%), rtf:anstiegHm, rtf:routingProfil,
                                         rtf:zielgruppe, rtf:folgtRadweg, gsp:hasGeometry (WKT)
 └ rtf:hatEtappe → rtf:Etappe ⊑ gdi:Streckenabschnitt
                   rtf:tagNummer, rtf:datum, gdi:laenge (m), rtf:maxSteigung, rtf:fahrzeitStunden, rtf:anteilRadweg/-Asphalt/-Hauptstrasse,
                   rtf:beginntBeiKnoten / rtf:endetBeiKnoten → rtf:Etappenpunkt ⊑ gdi:Knoten
                                                              └ gdi:befindetIn → gdi:Gemeinde (gdi:schluessel = ARS, owl:sameAs wd:Q…)
                   rtf:uebernachtungIn / rtf:unterkunftsvorschlag → rtf:Unterkunft (schema:Hotel, schema:Campground …)
                   rtf:notausstieg → rtf:Bahnhof (schema:TrainStation)
                   rtf:hatWetter → rtf:Wetterlage
 rtf:Anfrage    rtf:anfrageText, rtf:parameter   (prov:wasGeneratedBy: was die Tour ausgelöst hat)
 Jeder Ort:     prov:wasDerivedFrom → rtf:Datensatz (dct:title, dct:license, dct:rightsHolder)
```

Präfixe: `rtf:` https://w3id.org/routify/ontologie# · `gdi:` https://registry.gdi-de.org/up3/ontology/ (GDI-DE-Radnetz-Ontologie v6, nur referenziert; die Registry-Adresse zeigt derzeit eine Fehlerseite, Doku: https://cprudhomme.github.io/gdi-anforderung-ontologie-radnetz-documentation/).

## Externe Dienste und Rückfälle

| Dienst | Rückfall bei Ausfall |
|---|---|
| Ollama (lokal) | Einstellungen-Formular plant ohne LLM |
| BRouter (lokal) | Wiederholung, Korridore verkleinern; Meldung im Chat |
| Photon | Cache → Offline-Ortsverzeichnis (7.383 Orte) |
| Bright Sky | Tour ohne Wetter, Hinweis |
| Overpass | Cache je Radweg; sonst normale Route mit Hinweis |
| Kartenkacheln | CyclOSM ist Standard; TopPlusOpen und OSM wählbar |
| Mapillary | ohne `MAPILLARY_TOKEN`: „Straßenfotos“ zeigt „nicht verfügbar“, Planung unberührt |
| Whisper (lokal) | Modell fehlt → einmaliger Download; sonst Eintippen |

## Messwerte (M1 Pro, 32 GB)

| Messung | Wert |
|---|---|
| LLM (qwen3:8b) je Anfrage | ca. 5 s |
| 15 Anfragen gleichzeitig (mit `OLLAMA_NUM_PARALLEL=6`) | Median 24 s, letzte 72 s (vorher nacheinander: 60 s / 94 s) |
| Routing Mainz–Koblenz (2 Varianten) | ca. 4 s (vorher mit 3 Varianten 9–11 s) |
| Routing Dresden–Magdeburg (250 km) | ca. 7 s (vorher 16–23 s) |
| Routing Hamburg–München (2 Korridore) | ca. 10 s (vorher 17–30 s) |
| Höhenauswertung 800 km | < 0,5 s |
| RDF-Graph Mainz–Koblenz | ca. 1.800 Tripel, < 0,5 s |
| Vorliebe „flach“ (BRouter-Parameter) | 512 → 426 Hm |
| Radfernweg Hamburg–Magdeburg | 94 % ≤ 300 m am Elberadweg |

## Tests

- `code/tests/test_api.py`: 18 End-to-End-Fälle (inkl. SHACL-Prüfung und Straßenfotos) gegen den laufenden Server, `schnell` lässt die LLM-Fälle weg
- `code/tests/test_llm_extraction.py`: Text → Parameter (inkl. Änderungen, Vorlieben, Wetterwünsche)
