"""Konten für Routify: Anmeldung, gespeicherte Touren, Voreinstellungen, Verlauf.

Speicherort: data/routify.db (SQLite, lokal, nicht im Git).
Passwörter werden nur als scrypt-Hash gespeichert; Anmeldung über ein Sitzungs-Cookie (30 Tage).
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "routify.db"
COOKIE = "routify_sitzung"
SITZUNG_SEKUNDEN = 30 * 24 * 3600
VOREINST_FELDER = ("zielgruppe", "fahrrad", "km_pro_tag", "unterkunft_typ")


def _db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init():
    with _db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS nutzer (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
            pw_hash BLOB NOT NULL, salt BLOB NOT NULL, voreinst TEXT DEFAULT '{}', erstellt REAL);
        CREATE TABLE IF NOT EXISTS sitzungen (
            token TEXT PRIMARY KEY, nutzer_id INTEGER NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE, ablauf REAL);
        CREATE TABLE IF NOT EXISTS touren (
            id INTEGER PRIMARY KEY, nutzer_id INTEGER NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
            name TEXT NOT NULL, notiz TEXT DEFAULT '', params TEXT NOT NULL, variante INTEGER,
            kurz TEXT DEFAULT '{}', erstellt REAL, geaendert REAL);
        CREATE TABLE IF NOT EXISTS verlauf (
            id INTEGER PRIMARY KEY, nutzer_id INTEGER NOT NULL REFERENCES nutzer(id) ON DELETE CASCADE,
            text TEXT NOT NULL, zeit REAL);
        """)


def _hash(passwort, salt):
    return hashlib.scrypt(passwort.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _neue_sitzung(con, nutzer_id):
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sitzungen VALUES (?, ?, ?)", (token, nutzer_id, time.time() + SITZUNG_SEKUNDEN))
    return token


def registrieren(name, passwort):
    name = (name or "").strip()
    if not (2 <= len(name) <= 40):
        raise ValueError("Der Name muss 2–40 Zeichen lang sein.")
    if len(passwort or "") < 6:
        raise ValueError("Das Passwort muss mindestens 6 Zeichen haben.")
    salt = secrets.token_bytes(16)
    with _db() as con:
        try:
            cur = con.execute("INSERT INTO nutzer (name, pw_hash, salt, erstellt) VALUES (?, ?, ?, ?)",
                              (name, _hash(passwort, salt), salt, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError("Diesen Namen gibt es schon.")
        return _neue_sitzung(con, cur.lastrowid)


def anmelden(name, passwort):
    with _db() as con:
        row = con.execute("SELECT id, pw_hash, salt FROM nutzer WHERE name = ?", ((name or "").strip(),)).fetchone()
        # Auch bei unbekanntem Namen hashen, damit die Antwortzeit nichts verrät
        pruef = _hash(passwort or "", row["salt"] if row else b"x" * 16)
        if not row or not hmac.compare_digest(pruef, row["pw_hash"]):
            raise ValueError("Name oder Passwort stimmt nicht.")
        return _neue_sitzung(con, row["id"])


def abmelden(token):
    with _db() as con:
        con.execute("DELETE FROM sitzungen WHERE token = ?", (token,))


def nutzer(token):
    """Angemeldeter Nutzer zum Cookie oder None."""
    if not token:
        return None
    with _db() as con:
        row = con.execute("""SELECT n.id, n.name, n.voreinst, s.ablauf FROM sitzungen s JOIN nutzer n ON n.id = s.nutzer_id
                             WHERE s.token = ?""", (token,)).fetchone()
        if not row or row["ablauf"] < time.time():
            return None
        return {"id": row["id"], "name": row["name"], "voreinst": json.loads(row["voreinst"] or "{}")}


# ---------------------------------------------------------------- Voreinstellungen

def voreinstellungen_speichern(nutzer_id, werte):
    v = {k: werte.get(k) for k in VOREINST_FELDER if werte.get(k) not in (None, "", [])}
    if "km_pro_tag" in v:
        v["km_pro_tag"] = max(10, min(300, float(v["km_pro_tag"])))
    with _db() as con:
        con.execute("UPDATE nutzer SET voreinst = ? WHERE id = ?", (json.dumps(v), nutzer_id))
    return v


# ---------------------------------------------------------------- Touren

def touren(nutzer_id):
    with _db() as con:
        rows = con.execute("SELECT id, name, notiz, variante, kurz, erstellt, geaendert, params FROM touren "
                           "WHERE nutzer_id = ? ORDER BY geaendert DESC", (nutzer_id,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "notiz": r["notiz"], "variante": r["variante"],
             "kurz": json.loads(r["kurz"] or "{}"), "params": json.loads(r["params"]),
             "erstellt": r["erstellt"], "geaendert": r["geaendert"]} for r in rows]


def tour_speichern(nutzer_id, name, params, variante=None, kurz=None, notiz=""):
    jetzt = time.time()
    with _db() as con:
        cur = con.execute("INSERT INTO touren (nutzer_id, name, notiz, params, variante, kurz, erstellt, geaendert) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (nutzer_id, (name or "Tour")[:80], notiz or "", json.dumps(params), variante,
                           json.dumps(kurz or {}), jetzt, jetzt))
        return cur.lastrowid


def tour_aendern(nutzer_id, tour_id, name=None, notiz=None):
    with _db() as con:
        if name is not None:
            con.execute("UPDATE touren SET name = ?, geaendert = ? WHERE id = ? AND nutzer_id = ?",
                        (name[:80], time.time(), tour_id, nutzer_id))
        if notiz is not None:
            con.execute("UPDATE touren SET notiz = ?, geaendert = ? WHERE id = ? AND nutzer_id = ?",
                        (notiz[:500], time.time(), tour_id, nutzer_id))
        return con.total_changes > 0


def tour_loeschen(nutzer_id, tour_id):
    with _db() as con:
        return con.execute("DELETE FROM touren WHERE id = ? AND nutzer_id = ?", (tour_id, nutzer_id)).rowcount > 0


# ---------------------------------------------------------------- Verlauf

def verlauf_merken(nutzer_id, text):
    text = (text or "").strip()
    if not text:
        return
    with _db() as con:
        con.execute("DELETE FROM verlauf WHERE nutzer_id = ? AND text = ?", (nutzer_id, text))  # keine Doppelten
        con.execute("INSERT INTO verlauf (nutzer_id, text, zeit) VALUES (?, ?, ?)", (nutzer_id, text, time.time()))
        con.execute("""DELETE FROM verlauf WHERE nutzer_id = ? AND id NOT IN
                       (SELECT id FROM verlauf WHERE nutzer_id = ? ORDER BY zeit DESC LIMIT 20)""", (nutzer_id, nutzer_id))


def verlauf(nutzer_id):
    with _db() as con:
        return [{"text": r["text"], "zeit": r["zeit"]} for r in
                con.execute("SELECT text, zeit FROM verlauf WHERE nutzer_id = ? ORDER BY zeit DESC", (nutzer_id,))]


init()
