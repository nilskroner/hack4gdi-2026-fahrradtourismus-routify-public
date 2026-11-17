@echo off
REM Routify starten (Windows) - ein Befehl fuer alles:
REM   1. Python-Umgebung .venv anlegen und Pakete installieren (nur beim ersten Mal / wenn requirements.txt neu ist)
REM   2. Pruefen, ob alles da ist (code\scripts\pruefen.py): beim ersten Mal BRouter, Routing-Daten und Whisper laden,
REM      Java, Ollama + Modell, Daten
REM   3. BRouter (Routing) in einem eigenen Fenster starten, dann das Backend; der Browser oeffnet sich
REM
REM   start.bat            starten
REM   start.bat pruefen    nur pruefen, nichts starten
REM Beenden: dieses Fenster schliessen bzw. Ctrl+C, dann das BRouter-Fenster schliessen.
cd /d "%~dp0"
chcp 65001 >nul

REM ---- 1. Python-Umgebung
if not exist .venv\Scripts\python.exe (
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if not exist .venv\Scripts\python.exe (
    echo [X] Python 3.11 oder neuer fehlt - siehe README, Abschnitt 1
    pause & exit /b 1
  )
)
fc /b requirements.txt .venv\requirements.txt >nul 2>nul
if errorlevel 1 (
  echo ... installiere Python-Pakete ^(einmalig, dauert 1-2 Minuten^)
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt || (pause & exit /b 1)
  copy /y requirements.txt .venv\requirements.txt >nul
)

REM ---- 2. Pruefen
.venv\Scripts\python code\scripts\pruefen.py || (pause & exit /b 1)
if /i "%1"=="pruefen" exit /b 0

REM ---- 3. Starten
start "BRouter (Routify)" /min cmd /c code\scripts\start_brouter.bat
echo [ok] BRouter gestartet (eigenes Fenster, minimiert)
start "" /b cmd /c "timeout /t 8 >nul & start http://localhost:8000"
echo ... Backend startet - dann http://localhost:8000 oeffnen
.venv\Scripts\python -m uvicorn app:app --app-dir code/backend --host 127.0.0.1 --port 8000
