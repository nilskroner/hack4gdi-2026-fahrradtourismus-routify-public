# Daten

Im Repo liegen nur die kleinen, aufbereiteten Daten (ca. 75 MB). Die großen Dateien lädt `code/scripts/pruefen.py`
beim ersten Start (`./start.sh` / `start.bat`) automatisch herunter, insgesamt ca. 1,4 GB.

## Wird beim ersten Start heruntergeladen (nicht im Git)

| Ordner | Inhalt | Wofür | Quelle, Lizenz |
|---|---|---|---|
| `brouter/app/brouter-1.7.10/` | BRouter-Server (`brouter-1.7.10-all.jar`) und Profile (`profiles2/`), ca. 7 MB | Routing-Server | [GitHub-Release v1.7.10](https://github.com/abrensch/brouter/releases/tag/v1.7.10), MIT; per SHA-256 geprüft |
| `brouter/segments4/*.rd5` | Routing-Daten ganz Deutschland und Grenzregionen (6 Kacheln, ca. 890 MB) | Routing, Wege & Untergrund, **Höhen** (SRTM) | [brouter.de/segments4](https://brouter.de/brouter/segments4/), aus OpenStreetMap (ODbL), Höhen SRTM (gemeinfrei) |
| `whisper/small/` | Spracherkennungsmodell faster-whisper „small“ (ca. 460 MB) | Spracheingabe, lokal | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small), MIT |

Die BRouter-Kacheln werden auf brouter.de regelmäßig aus aktuellen OSM-Daten neu erzeugt. Zum Aktualisieren
`data/brouter/segments4/` löschen und neu starten.

## Im Repo

| Ordner / Datei | Inhalt | Wofür | Herkunft |
|---|---|---|---|
| `prepared/pois.json` | 45.835 Unterkünfte und 15.913 Fahrrad-POIs (Läden, Verleih, Reparaturstationen) | Unterkünfte, Fahrrad-POIs, Wunsch-Stopps | OpenStreetMap (ODbL), erzeugt mit `code/scripts/prepare_data.py` |
| `prepared/bahnhoefe.json` | 11.325 Bahnhöfe mit Gemeinde und amtlichem Schlüssel (ARS/AGS) | Notausstiege, Gemeinden | BKG POI-Open (dl-de/by-2.0), erzeugt mit `prepare_data.py` |
| `prepared/wikidata_gemeinden.json` | 11.531 Gemeinden: AGS → Wikidata-ID | Linked Data (`owl:sameAs`) | Wikidata (P439), CC0 |
| `radrouten/index.json` | 6.546 OSM-Radrouten-Relationen (2.894 Namen) | Radfernwege erkennen („Elberadweg“) | OpenStreetMap (ODbL), Overpass |
| `radrouten/geometrie/*.json` | Verlauf einzelner Radfernwege | Cache, wird bei Bedarf per Overpass ergänzt | OpenStreetMap (ODbL) |
| `osm-unterkuenfte/unterkuenfte_de_2026-11-13.geojson` | 57.962 Unterkünfte (Rohdaten) | nur für `prepare_data.py` | OpenStreetMap (ODbL), Overpass-Export 13.11.2026 |
| `osm-fahrrad/fahrrad-poi_de_2026-11-13.geojson` | 18.312 Fahrrad-POIs (Rohdaten, ohne Abstellanlagen) | nur für `prepare_data.py` | OpenStreetMap (ODbL), Overpass-Export 13.11.2026 |

Live per Internet: Wetter (Bright Sky / DWD), Ortssuche (Photon), Hintergrundkarten, neue Radfernweg-Verläufe (Overpass).

Entsteht beim Start (nicht im Git): `routify.db` (Konten, gespeicherte Touren), `prepared/ortssuche_cache.json`
(Zwischenspeicher der Ortssuche), `zertifikat/` (für `start.sh teilen`), `brouter/customprofiles/`.

## Daten neu aufbereiten

Nur nötig, wenn sich die Rohdaten ändern. Für die Bahnhöfe braucht es zusätzlich GDAL (`ogr2ogr`). POI-Open
(BKG, ca. 30 MB) wird dabei einmalig nach `data/poi-open/` geladen.

```sh
.venv/bin/python code/scripts/prepare_data.py
```

## Quellenangaben

© OpenStreetMap-Mitwirkende (ODbL) · © BKG, Datenlizenz Deutschland – Namensnennung 2.0 (POI-Open) ·
Wikidata (CC0) · Höhen: SRTM (NASA, gemeinfrei) über BRouter
