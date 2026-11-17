"""Spracheingabe lokal mit Whisper (faster-whisper) – das Audio verlässt den Rechner nicht.

- Modell: data/whisper/<WHISPER_MODELL> (Standard "small", ca. 460 MB, nicht im Repo).
  Wird beim ersten Start (code/scripts/pruefen.py) bzw. spätestens hier einmalig von Hugging Face
  (Systran/faster-whisper-…) geladen.
- Der Browser nimmt mit MediaRecorder auf (webm/opus, Safari mp4) und schickt die Bytes an POST /api/sprache.
- Gemessen (M1 Pro, CPU, int8): ca. 1 s Rechenzeit für 9 s Sprache.
"""
import os
import tempfile
import threading
import time

from konfig import ROOT

MODELL = os.getenv("WHISPER_MODELL", "small")
ORDNER = ROOT / "data" / "whisper" / MODELL
# Fachbegriffe als Hinweis, damit Whisper sie richtig schreibt
HINWEIS = ("Radtour mit Etappen, km am Tag, Campingplatz, Pension, E-Bike, Gravelbike, Rundtour, "
           "Elberadweg, Weserradweg, Rheinradweg, Notausstieg, Bahnhof, Freibad.")
# typische Whisper-Halluzinationen bei Stille
UNSINN = ("untertitel", "copyright", "amara.org", "vielen dank fürs zuschauen", "swr", "zdf")

_modell, _sperre = None, threading.Lock()
FEHLER = None


def modell():
    """Lädt das Modell einmal (thread-sicher). Ohne Ordner: einmalig herunterladen."""
    global _modell, FEHLER
    with _sperre:
        if _modell is None:
            try:
                from faster_whisper import WhisperModel
                if not (ORDNER / "model.bin").exists():
                    from huggingface_hub import snapshot_download
                    snapshot_download(f"Systran/faster-whisper-{MODELL}", local_dir=str(ORDNER))
                _modell = WhisperModel(str(ORDNER), device="cpu", compute_type="int8")
                FEHLER = None
            except Exception as e:  # z. B. Paket fehlt, kein Modell und kein Internet
                FEHLER = f"{type(e).__name__}: {e}"
                raise
    return _modell


def status():
    if _modell is not None:
        return f"Whisper {MODELL} (lokal)"
    if FEHLER:
        return f"nicht verfügbar ({FEHLER[:80]})"
    return f"Whisper {MODELL} (lokal, lädt beim ersten Gebrauch)" if (ORDNER / "model.bin").exists() \
        else f"Modell fehlt in data/whisper/{MODELL} (wird bei Bedarf geladen)"


def transkribieren(daten: bytes, endung: str = ".webm") -> dict:
    """Audio-Bytes -> {"text", "sekunden", "dauer"}; Aufrufe laufen nacheinander (Modell nicht doppelt belasten)."""
    t0 = time.time()
    m = modell()
    with tempfile.NamedTemporaryFile(suffix=endung, delete=False) as f:
        f.write(daten)
        pfad = f.name
    try:
        with _sperre:
            segmente, info = m.transcribe(pfad, language="de", beam_size=1, vad_filter=True,
                                          initial_prompt=HINWEIS, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segmente).strip()
    finally:
        os.unlink(pfad)
    if any(w in text.lower() for w in UNSINN) and len(text) < 80:
        text = ""
    return {"text": text, "sekunden": round(time.time() - t0, 2), "dauer": round(info.duration, 1)}
