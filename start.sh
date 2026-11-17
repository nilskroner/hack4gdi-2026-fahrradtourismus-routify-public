#!/bin/sh
# Routify starten (macOS / Linux) – ein Befehl für alles:
#   1. Python-Umgebung .venv anlegen und Pakete installieren (nur beim ersten Mal / wenn requirements.txt neu ist)
#   2. Prüfen, ob alles da ist (code/scripts/pruefen.py): beim ersten Mal BRouter, Routing-Daten und Whisper laden,
#      Java, Ollama + Modell, Daten
#   3. BRouter (Routing) im Hintergrund starten, dann das Backend; der Browser öffnet sich von selbst
#
#   ./start.sh            starten
#   ./start.sh teilen     auch für Handys im selben WLAN (QR-Code unter http://localhost:8000/teilen)
#   ./start.sh pruefen    nur prüfen, nichts starten
# Beenden mit Ctrl+C (BRouter wird mit beendet).
cd "$(dirname "$0")" || exit 1

# ---- 1. Python-Umgebung
PY=""
for p in python3.13 python3.12 python3.11 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then PY="$p"; break; fi
done
if [ ! -x .venv/bin/python ]; then
  [ -n "$PY" ] || { echo "✗ Python 3.11 oder neuer fehlt (siehe README, Abschnitt 1)"; exit 1; }
  echo "… lege Python-Umgebung .venv an ($PY)"
  "$PY" -m venv .venv || exit 1
fi
if ! cmp -s requirements.txt .venv/.requirements.txt; then
  echo "… installiere Python-Pakete (einmalig, dauert 1–2 Minuten)"
  .venv/bin/python -m pip install -q --upgrade pip && .venv/bin/python -m pip install -q -r requirements.txt || exit 1
  cp requirements.txt .venv/.requirements.txt
fi

# ---- 2. Prüfen
.venv/bin/python code/scripts/pruefen.py || exit 1
[ "$1" = "pruefen" ] && exit 0

# ---- 3. Starten
if curl -s -o /dev/null http://localhost:8000/api/health; then
  echo "✗ Port 8000 ist schon belegt – läuft Routify bereits? (sonst das andere Programm beenden)"; exit 1
fi
./code/scripts/start_brouter.sh > /tmp/routify-brouter.log 2>&1 &
PIDS=$!
trap 'kill $PIDS 2>/dev/null' EXIT INT TERM
echo "✓ BRouter gestartet (Log: /tmp/routify-brouter.log)"

HOST=127.0.0.1
if [ "$1" = "teilen" ]; then
  HOST=0.0.0.0
  command -v openssl >/dev/null || echo "⚠ openssl fehlt – ohne HTTPS geht am Handy keine Spracheingabe"
  # HTTPS-Tor auf Port 8443, damit Handys auch das Mikrofon nutzen dürfen (selbst ausgestelltes Zertifikat)
  .venv/bin/python code/scripts/https_tor.py &
  PIDS="$PIDS $!"
  trap 'kill $PIDS 2>/dev/null' EXIT INT TERM
  echo "✓ Teilen an – QR-Code: http://localhost:8000/teilen"
fi

# Sobald das Backend antwortet: Status zeigen und Browser öffnen (ROUTIFY_KEIN_BROWSER=1 schaltet das ab)
(
  for _ in $(seq 1 90); do
    sleep 1
    if curl -s -o /dev/null http://localhost:8000/api/health; then
      echo "✓ Routify läuft: http://localhost:8000   (Status: http://localhost:8000/api/health)"
      if [ -z "$ROUTIFY_KEIN_BROWSER" ]; then
        URL=http://localhost:8000; [ "$1" = "teilen" ] && URL=http://localhost:8000/teilen
        (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") >/dev/null 2>&1
      fi
      exit 0
    fi
  done
  echo "⚠ Backend antwortet nach 90 s noch nicht – Ausgabe oben prüfen"
) &

echo "… Backend startet (erste Anfrage lädt das Sprachmodell, ca. 10 s)"
.venv/bin/python -m uvicorn app:app --app-dir code/backend --host $HOST --port 8000
