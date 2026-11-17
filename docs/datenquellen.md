# Datenquellen & Dienste

Routify (bundesweit, beliebige Routen A → B). Alle hier genannten Daten sind offen lizenziert.

---

## 1. Überblick

```
                         ┌──────────────── lokal auf dem Laptop ────────────────┐
Browser ── localhost:8000 ─► Backend (FastAPI) ──► BRouter :17777 (Routing,    │
   │                         │        │             Höhen) └ data/brouter/      │
   │                         │        └─────────► Ollama :11434 (LLM qwen3:8b) │
   │                         └ data/prepared/  (Unterkünfte, Fahrrad-POIs,     │
   │                                            Bahnhöfe, Wikidata-Gemeinden)  │
   │                         └──────────────────────────────────────────────────┘
   │                         │
   │                         └── Internet: Photon (Ortssuche), Bright Sky (Wetter)
   └── Internet: Kartenkacheln (CyclOSM, TopPlusOpen, OSM), Radnetz-WMS
       (Leaflet, Chart.js und Spracherkennung liegen lokal)
```

---

## 2. Daten, die der Prototyp nutzt

| Was | Datei / Ort | Quelle | Umfang | Lizenz | Wofür |
|---|---|---|---|---|---|
| Routing-Graph inkl. Wegmerkmalen und Höhen | `data/brouter/segments4/` (wird beim ersten Start geladen) | BRouter-Segmente (aus OpenStreetMap + SRTM-Höhen) | 6 Kacheln, ganz DE + Grenzregionen, ca. 890 MB | ODbL (OSM), SRTM gemeinfrei | Routen, **Wege & Untergrund**, Brücken/Tunnel, **Höhenprofil, Höhenmeter, max. Steigung** (alle 50 m, Brücken/Tunnel überbrückt) |
| Unterkünfte | → `data/prepared/pois.json` | OpenStreetMap, Overpass-Export 13.11.2026 | 45.835: Hotel, Pension, Camping, Hostel, Motel (Ferienwohnungen bewusst ausgelassen) | ODbL | Unterkünfte je Etappe, gewünschte Unterkunftsart zuerst |
| Fahrrad-POIs | → `data/prepared/pois.json` | OpenStreetMap, Overpass-Export 13.11.2026 | Läden 6.186 · Verleih 4.975 · Reparaturstationen 4.752 (ohne Abstellanlagen) | ODbL | POIs entlang der Route; **Wunsch-Stopps** („mit Fahrradwerkstatt unterwegs“) |
| Bahnhöfe | → `data/prepared/bahnhoefe.json` | BKG POI-Open, Ebene Haltestellen | 11.325 Stationen mit Zugverkehr | dl-de/by-2.0 | **Notausstiege**: alle Bahnhöfe ≤ 5 km um die Route werden immer berechnet, aber **nur auf Wunsch angezeigt** (Anfrage wie „falls ich nicht mehr kann“ oder Klick). Außerdem: Zwischenorte bei langen Strecken und Rundtouren, Zielvorschläge |
| Radfernwege (Elberadweg, D-Routen …) | `data/radrouten/index.json` + `geometrie/` (Cache) | OpenStreetMap-Radrouten, Overpass | Index 6.546 Relationen / 2.894 Namen; Verlauf je Radweg bei Bedarf | ODbL | Route folgt dem genannten Radweg |
| Gemeinden ↔ Wikidata | → `data/prepared/wikidata_gemeinden.json` | Wikidata (Eigenschaft P439 Amtlicher Gemeindeschlüssel), einmalig per SPARQL | 11.531 Gemeinden | CC0 | **Linked Data:** Etappenorte und Notausstiege → `gdi:Gemeinde` mit `owl:sameAs` Wikidata; Brücke über den ARS aus POI-Open (99,8 % der Bahnhöfe zugeordnet) |
| Offline-Ortsverzeichnis | im Speicher, aus Bahnhöfen und OSM | eigene Ableitung | – | wie Quellen | Rückfall, wenn die Ortssuche (Photon) nicht erreichbar ist |

Aufbereitung: `code/scripts/prepare_data.py` (Rohdaten → `data/prepared/`). POIs mit Wikidata-ID erscheinen im RDF mit `owl:sameAs`.

### Semantisches Modell

`code/ontologie/routify.ttl`: Routify-Ontologie, ausgerichtet an der **GDI-DE-Radnetz-Ontologie v6** (Entwurf, laut README Autorin Dr. Claire Ponciano, für GDI-DE und BALM; [Repo](https://github.com/Cprudhomme/gdi-anforderung-ontologie-radnetz-documentation), [Doku](https://cprudhomme.github.io/gdi-anforderung-ontologie-radnetz-documentation/); verwandt: [BALM-Codelisten Radnetz](https://registry.gdi-de.org/codelist/de.bund.balm.radnetz), nur per `owl:imports` referenziert). Jede Datenquelle oben ist darin als `rtf:Datensatz` mit Lizenz beschrieben; jeder Ort einer Planung verweist per `prov:wasDerivedFrom` auf seinen Datensatz.

---

## 3. Dienste – was läuft wo

### Lokal (auf dem eigenen Laptop)

| Dienst | Adresse | Software | Wofür | Start |
|---|---|---|---|---|
| Backend + Oberfläche | http://localhost:8000 | Python / FastAPI (`code/backend/`, Module siehe `architektur.md`) | API `/api/plan`, `/api/rdf`, `/api/sparql`, Status `/api/health`, Webseite, `/static`, `/assets`, `/ontologie/routify.ttl` | `start.sh` / `start.bat` |
| Routing | http://localhost:17777 | BRouter 1.7.10 (Java, wird beim ersten Start geladen) | 2 Routenvarianten (lange Strecken: 2 Korridore), Profile safety/trekking/fastbike/gravel/mtb, im Expertenmodus auch shortest | `code/scripts/start_brouter.sh` |
| Sprachmodell | http://localhost:11434 | Ollama + `qwen3:8b` (~5 GB) | Anfrage → Parameter (Start, Ziel, Tage, km/Tag, Zielgruppe, Rad, Unterkunft, Wunsch-Stopps, Notausstiege, Radfernweg, Rundtour); Vorlieben und Wetterwünsche erkennen zusätzlich Wortlisten; versteht Änderungen an der laufenden Planung. Mit „Einstellungen“ nicht nötig | Ollama-App / `ollama serve` |
| Spracheingabe | – | Whisper `small` im Backend (`POST /api/sprache`), Aufnahme im Browser per MediaRecorder | Sprache → Text; ✅ Audio verlässt den Rechner nicht | im Backend |

### Im Internet (öffentliche Dienste, kein Key nötig)

| Dienst | Adresse | Wofür | Hinweis |
|---|---|---|---|
| Photon (komoot) | photon.komoot.io | Ortsname → Koordinate | Fair Use; Cache + Offline-Ortsverzeichnis als Rückfall; für Dauerbetrieb eigene Instanz |
| Wikidata Query Service | query.wikidata.org | Gemeindeschlüssel → Wikidata-ID | nur bei `prepare_data.py`, nicht zur Laufzeit |
| Overpass API | overpass-api.de (+ overpass.kumi.systems als Ausweich-Server) | Verlauf eines Radfernwegs, nur beim ersten Abruf | danach lokal gespeichert |
| Bright Sky | api.brightsky.dev | Wetter je Etappenende (DWD-Daten) | Quellenangabe DWD; Vorhersage bis ca. 10 Tage |
| CyclOSM | tile-cyclosm.openstreetmap.fr | **Standardkarte** „Fahrradkarte“ | Fair Use |
| TopPlusOpen (BKG) | sgx.geodatenzentrum.de | Amtliche Hintergrundkarte (farbig und grau) | offen |
| OpenStreetMap-Kacheln | tile.openstreetmap.org | Hintergrundkarte | Fair Use, nicht für Dauerbetrieb |
| Radnetz Deutschland (BALM, WMS) | radroutenplaner-deutschland.de/geoserver | Overlay D-Routen | amtlich |
| Waymarked Trails | tile.waymarkedtrails.org | Overlay Radfernwege | CC-BY-SA |

### Nur beim ersten Start (Downloads)

| Was | Adresse |
|---|---|
| BRouter 1.7.10 | github.com/abrensch/brouter/releases |
| BRouter-Kacheln | brouter.de/brouter/segments4 |
| Whisper small | huggingface.co/Systran/faster-whisper-small |
| Sprachmodell qwen3:8b | über `ollama pull` (fragt vorher) |

### Optional mit eigenem Key (`.env`)

| Dienst | Wofür |
|---|---|
| Thunderforest (OpenCycleMap), `THUNDERFOREST_KEY` | weitere Fahrradkarte |
| Mapillary, `MAPILLARY_TOKEN` | Straßenfotos auf dem Track, erst beim Aufklappen; Bilder über unseren Server (Browser spricht nicht mit Meta); Fotos CC BY-SA 4.0, Namensnennung Fotograf + Mapillary |

---

## 4. Hinweise für den Dauerbetrieb

- Fair Use der öffentlichen Dienste (Photon, Overpass, OSM-Kacheln, CyclOSM) beachten bzw. eigene Instanzen betreiben.
- Quellenangaben stehen in der Karte (Attribution), im GPX-Export und im RDF (`dct:license` je Datensatz).

---

## 5. Hintergrund: Hackathon-Version

Routify entstand beim hack4GDI (13./14.11.2026). Die dort eingereichte Version nutzte zusätzlich Daten, die nur für den
Hackathon freigegeben waren (BKG DGM25 für Höhen, BKG POI-Bund für Stopps wie Supermarkt oder Schwimmbad, ADFC Bett+Bike
für Unterkünfte), sowie Mapbox als Standardkarte mit 3D-Ansicht. In dieser öffentlichen Version sind sie ersetzt bzw. entfernt:

| Hackathon-Version | Öffentliche Version |
|---|---|
| Höhen aus BKG DGM25 (25 m) | Höhen aus den BRouter-Kacheln (SRTM, ca. 90 m) – gleiche Auswertung |
| Wunsch-Stopps aus BKG POI-Bund (Supermarkt, Schwimmbad, Museum, Apotheke, Krankenhaus, Geldautomat) | Wunsch-Stopps aus OSM: Fahrradwerkstatt, Fahrradverleih |
| Unterkünfte OSM + ADFC Bett+Bike (bevorzugt, mit Adresse und Telefon) | Unterkünfte aus OSM |
| Mapbox (2D + 3D) | CyclOSM, TopPlusOpen, OSM |

Weitere vom Hackathon bereitgestellte, offene Quellen (nicht genutzt): BALM Radnetz Deutschland als GeoPackage (genutzt nur
als WMS), BKG VG250, LVermGeo RP Basis-DLM, DB OpenStation API, DB InfraGO Streckennetz.
