"""Prüft, ob alles für Routify da ist, und bereitet den Start vor.

1. Große Dateien herunterladen (nur beim ersten Start, liegen nicht im Repo):
   - BRouter 1.7.10 (Routing-Server + Profile) von GitHub, ca. 7 MB, per SHA-256 geprüft
   - BRouter-Routingdaten Deutschland (6 Kacheln, ca. 890 MB) von brouter.de – aus OpenStreetMap, mit Höhen (SRTM)
   - Spracherkennung Whisper „small“ (ca. 460 MB) von Hugging Face – optional, ohne geht nur die Texteingabe
2. Software prüfen: Python-Pakete, Java 17+, Ollama und das Sprachmodell (bei Bedarf starten/laden).
3. Daten prüfen: Routing, aufbereitete POIs, Bahnhöfe, Radfernwege, Whisper.

Aufruf (wird von start.sh / start.bat erledigt):
  .venv/bin/python code/scripts/pruefen.py                 prüfen und fehlende Dateien laden
  .venv/bin/python code/scripts/pruefen.py --ohne-ollama   Ollama nicht prüfen
Rückgabewert 0 = startklar, 1 = es fehlt etwas Wichtiges.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

BROUTER_VERSION = "1.7.10"
BROUTER_DIR = DATA / "brouter" / "app" / f"brouter-{BROUTER_VERSION}"
BROUTER_ZIP = (f"https://github.com/abrensch/brouter/releases/download/v{BROUTER_VERSION}/brouter-{BROUTER_VERSION}.zip",
               "023fec3ba997758e8cd7ab9e1bae52e962af3f00b57683e3de86b84ffad01532")
SEGMENTE_URL = "https://brouter.de/brouter/segments4/{}.rd5"
SEGMENTE_DIR = DATA / "brouter" / "segments4"
KACHELN = ["E5_N45", "E5_N50", "E5_N55", "E10_N45", "E10_N50", "E15_N50"]  # ganz Deutschland + Grenzregionen
WHISPER_MODELL = os.getenv("WHISPER_MODELL", "small")
WHISPER_DIR = DATA / "whisper" / WHISPER_MODELL

sys.path.insert(0, str(ROOT / "code" / "backend"))
from konfig import HTTP_HEADERS, LLM_MODEL, OLLAMA_URL  # noqa: E402  (liest auch .env)

fehler, hinweise = [], []
OK, WARN, FEHLT = "✓", "⚠", "✗"
if os.name == "nt" or not (sys.stdout.encoding or "").lower().startswith("utf"):
    OK, WARN, FEHLT = "[ok]", "[!]", "[X]"


def melde(zeichen, text):
    print(f"  {zeichen} {text}")


def sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- Downloads
def laden(url, ziel, text):
    """Datei nach `ziel` laden (über .tmp, damit ein Abbruch keine halbe Datei hinterlässt), mit Fortschritt."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
        gesamt = int(r.headers.get("Content-Length") or 0)
        geladen, zuletzt = 0, 0.0
        while block := r.read(1024 * 1024):
            out.write(block)
            geladen += len(block)
            if time.time() - zuletzt > 0.5 or geladen == gesamt:
                zuletzt = time.time()
                anteil = f" ({geladen * 100 // gesamt} %)" if gesamt else ""
                print(f"\r  … {text}: {geladen / 1e6:.0f}{f' / {gesamt / 1e6:.0f}' if gesamt else ''} MB{anteil}   ",
                      end="", flush=True)
    print()
    tmp.replace(ziel)


def lade_brouter():
    if (BROUTER_DIR / f"brouter-{BROUTER_VERSION}-all.jar").exists() and (BROUTER_DIR / "profiles2" / "trekking.brf").exists():
        return
    url, pruefsumme = BROUTER_ZIP
    zipdatei = DATA / "brouter" / "app" / f"brouter-{BROUTER_VERSION}.zip"
    try:
        laden(url, zipdatei, f"BRouter {BROUTER_VERSION}")
        if sha256(zipdatei) != pruefsumme:
            raise RuntimeError("Prüfsumme stimmt nicht")
        # nur Server-JAR und Profile entpacken (das ZIP enthält auch die Android-App)
        with zipfile.ZipFile(zipdatei) as z:
            for name in z.namelist():
                rel = name.split("/", 1)[1] if "/" in name else ""
                if rel == f"brouter-{BROUTER_VERSION}-all.jar" or (rel.startswith("profiles2/") and not name.endswith("/")):
                    ziel = BROUTER_DIR / rel
                    ziel.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(ziel, "wb") as out:
                        shutil.copyfileobj(src, out)
        melde(OK, f"BRouter {BROUTER_VERSION} geladen")
    except Exception as e:
        fehler.append(f"BRouter konnte nicht geladen werden ({e}) – Internet prüfen und erneut starten")
        melde(FEHLT, fehler[-1])
    finally:
        zipdatei.unlink(missing_ok=True)


def lade_segmente():
    fehlend = [k for k in KACHELN if not (SEGMENTE_DIR / f"{k}.rd5").exists()]
    if not fehlend:
        return
    print(f"  … Routing-Daten fehlen ({len(fehlend)} von {len(KACHELN)} Kacheln, zusammen bis zu 890 MB) – lade von brouter.de")
    for k in fehlend:
        try:
            laden(SEGMENTE_URL.format(k), SEGMENTE_DIR / f"{k}.rd5", f"Kachel {k}")
        except Exception as e:
            fehler.append(f"Routing-Kachel {k} konnte nicht geladen werden ({e}) – Internet prüfen und erneut starten")
            melde(FEHLT, fehler[-1])
            return
    melde(OK, "Routing-Daten geladen")


def lade_whisper():
    if (WHISPER_DIR / "model.bin").exists() or importlib.util.find_spec("faster_whisper") is None:
        return
    print(f"  … lade Spracherkennung Whisper „{WHISPER_MODELL}“ von Hugging Face (ca. 460 MB, einmalig)")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(f"Systran/faster-whisper-{WHISPER_MODELL}", local_dir=str(WHISPER_DIR))
        melde(OK, "Whisper geladen")
    except Exception as e:
        hinweise.append(f"Whisper konnte nicht geladen werden ({type(e).__name__}) – Spracheingabe aus, Text geht")
        melde(WARN, hinweise[-1])


# ---------------------------------------------------------------- Software
def pruefe_python():
    v = sys.version_info
    if v < (3, 11):
        fehler.append(f"Python {v.major}.{v.minor} – mindestens 3.11 nötig")
        melde(FEHLT, fehler[-1])
    else:
        melde(OK, f"Python {v.major}.{v.minor}")
    pakete = {"fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx", "shapely": "shapely", "numpy": "numpy",
              "rdflib": "rdflib", "pyshacl": "pyshacl"}
    fehlend = [n for n, mod in pakete.items() if importlib.util.find_spec(mod) is None]
    if fehlend:
        fehler.append(f"Python-Pakete fehlen: {', '.join(fehlend)} → pip install -r requirements.txt")
        melde(FEHLT, fehler[-1])
    else:
        melde(OK, "Python-Pakete")
    if importlib.util.find_spec("faster_whisper") is None:
        hinweise.append("faster-whisper fehlt – Spracheingabe aus (Texteingabe geht)")
        melde(WARN, hinweise[-1])


def pruefe_java():
    java = shutil.which("java")
    if not java:
        fehler.append("Java fehlt (mind. Version 17) – siehe README, Abschnitt Installation")
        melde(FEHLT, fehler[-1])
        return
    try:
        aus = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30).stderr
    except Exception as e:  # z. B. macOS-Platzhalter „java“ ohne installiertes JDK
        aus = str(e)
    m = re.search(r'version "(\d+)(?:\.(\d+))?', aus)
    if not m:
        fehler.append("Java nicht nutzbar (java -version liefert keine Version) – JDK 17+ installieren")
        melde(FEHLT, fehler[-1])
        return
    major = int(m.group(1)) if m.group(1) != "1" else int(m.group(2) or 0)
    if major < 17:
        fehler.append(f"Java {major} – mindestens 17 nötig")
        melde(FEHLT, fehler[-1])
    else:
        melde(OK, f"Java {major}")


def _ollama_modelle():
    with urllib.request.urlopen(OLLAMA_URL.rstrip("/") + "/api/tags", timeout=3) as r:
        return [m["name"] for m in json.load(r).get("models", [])]


def pruefe_ollama():
    try:
        modelle = _ollama_modelle()
    except Exception:
        ollama = shutil.which("ollama")
        if not ollama:
            fehler.append("Ollama fehlt – installieren (siehe README) und starten")
            melde(FEHLT, fehler[-1])
            return
        print("  … Ollama läuft nicht – starte 'ollama serve' im Hintergrund")
        flags = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}  # DETACHED_PROCESS
        subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        modelle = None
        for _ in range(20):
            time.sleep(1)
            try:
                modelle = _ollama_modelle()
                break
            except Exception:
                pass
        if modelle is None:
            fehler.append("Ollama startet nicht – Ollama-App öffnen bzw. 'ollama serve' ausführen")
            melde(FEHLT, fehler[-1])
            return
    melde(OK, f"Ollama läuft ({OLLAMA_URL})")
    if any(m == LLM_MODEL or m == LLM_MODEL + ":latest" for m in modelle):
        melde(OK, f"Sprachmodell {LLM_MODEL}")
        return
    if sys.stdin.isatty() and shutil.which("ollama"):
        antwort = input(f"  ? Sprachmodell {LLM_MODEL} fehlt. Jetzt laden (ca. 5 GB)? [J/n] ").strip().lower()
        if antwort in ("", "j", "ja", "y", "yes"):
            if subprocess.run(["ollama", "pull", LLM_MODEL]).returncode == 0:
                melde(OK, f"Sprachmodell {LLM_MODEL} geladen")
                return
    fehler.append(f"Sprachmodell {LLM_MODEL} fehlt → ollama pull {LLM_MODEL}")
    melde(FEHLT, fehler[-1])


# ---------------------------------------------------------------- Daten
def pruefe_daten():
    def da(rel, text, wichtig=True):
        if (DATA / rel).exists():
            melde(OK, text)
            return True
        (fehler if wichtig else hinweise).append(f"{text}: data/{rel} fehlt")
        melde(FEHLT if wichtig else WARN, (fehler if wichtig else hinweise)[-1])
        return False

    da(f"brouter/app/brouter-{BROUTER_VERSION}/brouter-{BROUTER_VERSION}-all.jar", "BRouter (Routing-Software)")
    da(f"brouter/app/brouter-{BROUTER_VERSION}/profiles2/trekking.brf", "BRouter-Profile")
    fehlend = [k for k in KACHELN if not (SEGMENTE_DIR / f"{k}.rd5").exists()]
    if fehlend:
        fehler.append(f"Routing-Daten fehlen: {', '.join(fehlend)} (data/brouter/segments4/)")
        melde(FEHLT, fehler[-1])
    else:
        melde(OK, "Routing-Daten Deutschland (6 Kacheln)")
    da("prepared/pois.json", "Unterkünfte und Fahrrad-POIs (OSM)")
    da("prepared/bahnhoefe.json", "Bahnhöfe (BKG POI-Open)")
    da("prepared/wikidata_gemeinden.json", "Wikidata-Gemeinden (Linked Data)", wichtig=False)
    da("radrouten/index.json", "Radfernwege (OSM)", wichtig=False)
    da(f"whisper/{WHISPER_MODELL}/model.bin", f"Spracherkennung Whisper {WHISPER_MODELL}", wichtig=False)


def main():
    print("Routify – Prüfung")
    print(" Downloads (nur beim ersten Start)")
    lade_brouter()
    lade_segmente()
    lade_whisper()
    if not fehler:
        melde(OK, "vollständig")
    print(" Software")
    pruefe_python()
    pruefe_java()
    if "--ohne-ollama" not in sys.argv:
        pruefe_ollama()
    print(" Daten")
    pruefe_daten()
    print()
    if fehler:
        print(f"{FEHLT} Nicht startklar – {len(fehler)} Problem(e):")
        for f in fehler:
            print(f"   - {f}")
        return 1
    print(f"{OK} Startklar" + (f" ({len(hinweise)} Hinweis(e), Start trotzdem möglich)" if hinweise else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
