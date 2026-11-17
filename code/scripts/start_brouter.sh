#!/bin/sh
# Startet den lokalen BRouter-Server auf Port 17777.
# Erwartet: data/brouter/app/brouter-1.7.10/ und data/brouter/segments4/*.rd5
cd "$(dirname "$0")/../.." || exit 1
B=data/brouter/app/brouter-1.7.10
mkdir -p data/brouter/customprofiles
exec java -Xmx2g -cp "$B/brouter-1.7.10-all.jar" btools.server.RouteServer \
  data/brouter/segments4 "$B/profiles2" data/brouter/customprofiles 17777 8
