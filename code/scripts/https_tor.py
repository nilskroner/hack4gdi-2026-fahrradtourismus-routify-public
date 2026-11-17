"""HTTPS-Tor für die Präsentation: nimmt verschlüsselte Verbindungen auf Port 8443 an und reicht sie an die
laufende App (http://127.0.0.1:8000) weiter. Nötig, weil Handybrowser das Mikrofon nur über HTTPS freigeben.

Das Zertifikat ist selbst ausgestellt (data/zertifikat/, nicht im Git) und gilt für die aktuelle Netzadresse.
Handys zeigen deshalb beim ersten Öffnen eine Warnung, die man einmal bestätigt.

Start: .venv/bin/python code/scripts/https_tor.py   (macht ./start.sh teilen automatisch)
"""
import asyncio
import socket
import ssl
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORDNER = ROOT / "data" / "zertifikat"
PORT, ZIEL = 8443, ("127.0.0.1", 8000)


def netz_adresse():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def zertifikat(ip):
    """Selbst ausgestelltes Zertifikat für localhost + Netzadresse; neu erzeugen, wenn sich die Adresse geändert hat."""
    ORDNER.mkdir(parents=True, exist_ok=True)
    crt, key, fuer = ORDNER / "routify.crt", ORDNER / "routify.key", ORDNER / "adresse.txt"
    if crt.exists() and key.exists() and fuer.exists() and fuer.read_text().strip() == ip:
        return crt, key
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                    "-keyout", str(key), "-out", str(crt), "-subj", "/CN=Routify (lokal)",
                    "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
                   check=True, capture_output=True)
    key.chmod(0o600)
    fuer.write_text(ip)
    return crt, key


async def weiterleiten(leser, schreiber):
    try:
        while daten := await leser.read(65536):
            schreiber.write(daten)
            await schreiber.drain()
    except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
        pass
    finally:
        try:
            schreiber.close()
        except Exception:
            pass


async def verbindung(c_leser, c_schreiber):
    try:
        z_leser, z_schreiber = await asyncio.open_connection(*ZIEL)
    except OSError:
        c_schreiber.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain; charset=utf-8\r\n"
                          b"Connection: close\r\n\r\nRoutify-Backend laeuft nicht (Port 8000).")
        c_schreiber.close()
        return
    await asyncio.gather(weiterleiten(c_leser, z_schreiber), weiterleiten(z_leser, c_schreiber))


async def main():
    ip = netz_adresse()
    crt, key = zertifikat(ip)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(crt, key)
    server = await asyncio.start_server(verbindung, "0.0.0.0", PORT, ssl=ctx)
    print(f"✓ HTTPS für Handys: https://{ip}:{PORT}  (QR-Code: http://localhost:8000/teilen)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
