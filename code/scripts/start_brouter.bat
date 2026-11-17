@echo off
REM Startet den lokalen BRouter-Server auf Port 17777 (Windows).
REM Erwartet: data\brouter\app\brouter-1.7.10\ und data\brouter\segments4\*.rd5
cd /d "%~dp0\..\.."
set B=data\brouter\app\brouter-1.7.10
if not exist data\brouter\customprofiles mkdir data\brouter\customprofiles
java -Xmx2g -cp "%B%\brouter-1.7.10-all.jar" btools.server.RouteServer data\brouter\segments4 "%B%\profiles2" data\brouter\customprofiles 17777 8
