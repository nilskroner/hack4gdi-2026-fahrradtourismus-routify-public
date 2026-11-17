# Code – Routify

```
code/
├── backend/            FastAPI (Python 3.11+); Einstieg app.py, Ablauf einer Planung in planung.py
├── frontend/
│   ├── index.html      Seitengerüst (drei Spalten: Chat | Aktuelle Planung | Karte)
│   ├── teilen.html     QR-Code-Seite zum Teilen im lokalen Netz
│   ├── static/css/     routify.css
│   ├── static/js/      grundlagen → karte → chat → planung → wegpunkte → export → linkeddaten
│   │                   → fotos → einstellungen → konto → start (klassische Skripte, gemeinsame globale Namen)
│   └── assets/         Banner, App-Symbol
├── ontologie/
│   └── routify.ttl     Routify-Ontologie (Tour ⊑ gdi:TouristenRoute, Etappe ⊑ gdi:Streckenabschnitt …)
├── scripts/
│   ├── pruefen.py      prüft Software + Daten, lädt beim ersten Start BRouter, Routing-Daten und Whisper (läuft in start.sh / start.bat)
│   ├── start_brouter.sh / .bat   lokaler BRouter-Server (Port 17777)
│   ├── https_tor.py    HTTPS auf Port 8443 für Handys (Mikrofon), reicht an Port 8000 weiter (`start.sh teilen`)
│   ├── prepare_data.py Rohdaten → data/prepared/ (Bahnhöfe mit ARS/AGS, OSM-POIs, Wikidata-Gemeinden)
└── tests/
    ├── test_api.py             18 End-to-End-Fälle gegen den laufenden Server (`schnell` = ohne LLM)
    └── test_llm_extraction.py  51 Anfragen: Text → Parameter, inkl. Änderungen, Vorlieben, Wetter
```

Modulplan, Ontologie und Messwerte: [docs/architektur.md](../docs/architektur.md).
Installation und Start: [README im Hauptordner](../README.md).

## Konfiguration

Umgebungsvariablen bzw. `.env` (Vorlage `.env.example`, wird nicht committet):

| Variable | Standard | Wofür |
|---|---|---|
| `OLLAMA_URL` / `LLM_MODEL` | `http://localhost:11434` / `qwen3:8b` | Sprachmodell |
| `BROUTER_URL` / `BROUTER_PARALLEL` | `http://localhost:17777` / `3` | Routing, gleichzeitige BRouter-Anfragen |
| `PHOTON_URL` | `https://photon.komoot.io` | Ortssuche |
| `WHISPER_MODELL` | `small` | Spracherkennung (`base` = schneller, ungenauer) |
| `MAPILLARY_TOKEN` | – | Straßenfotos (optional; eigener Client token von mapillary.com/dashboard/developers) |
| `THUNDERFOREST_KEY` | – | OpenCycleMap (optional) |

## API

| Endpunkt | Zweck |
|---|---|
| `POST /api/plan` | `{text, params?, vorher?}` → Planung oder Rückfrage |
| `POST /api/rdf` | Planung → Turtle / JSON-LD |
| `GET /api/sparql/abfragen` · `POST /api/sparql` | vordefinierte SPARQL-Fragen auf der Planung |
| `POST /api/pruefen` | SHACL-Prüfung: Wünsche als Regeln gegen die Tour |
| `POST /api/fotos`, `GET /api/foto/{id}` | Straßenfotos (Mapillary) auf dem Track, Bilder über den Server |
| `GET /teilen`, `GET /api/teilen` | QR-Code-Seite zum Teilen im lokalen Netz |
| `POST /api/sprache` | Audio (webm/ogg/mp4/wav) → Text, lokal mit Whisper |
| `GET /ontologie/routify.ttl` | Ontologie |
| `GET /api/health` | Status aller Dienste und Daten |
| `/api/konto/*` | Anmelden, Touren, Voreinstellungen, Verlauf |
