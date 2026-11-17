"""Konfiguration: Pfade, .env, Dienst-Adressen."""
from pathlib import Path
import os




ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / "data" / "prepared"
FRONTEND = ROOT / "code" / "frontend"

# .env im Repo-Root einlesen (KEY=wert pro Zeile, Vorlage: .env.example), ohne Umgebungsvariablen zu überschreiben.
# Leere Werte werden ignoriert.
ENV_QUELLE = {}
for _env in (ROOT / ".env",):
    if _env.exists():
        for _line in _env.read_text(encoding="utf-8-sig").splitlines():  # -sig: BOM von Windows-Editoren ignorieren
            if "=" in _line and not _line.lstrip().startswith("#"):
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                if _v and not os.environ.get(_k):
                    os.environ[_k] = _v
                    ENV_QUELLE[_k] = _env.name

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
BROUTER_URL = os.getenv("BROUTER_URL", "http://localhost:17777")
PHOTON_URL = os.getenv("PHOTON_URL", "https://photon.komoot.io")
HTTP_HEADERS = {"User-Agent": "routify-prototype/0.1"}

