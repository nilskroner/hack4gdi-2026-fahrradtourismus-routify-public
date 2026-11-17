"""Höhen entlang einer Route aus den BRouter-Routingdaten.

Die BRouter-Kacheln (data/brouter/segments4/*.rd5) enthalten zu jedem Punkt eine Höhe (SRTM, ca. 90 m Raster).
BRouter liefert sie als dritte Koordinate im GeoJSON mit. Daraus entsteht hier ein Profil im festen Abstand,
mit Höhenmetern (Hysterese) und maximaler Steigung; Brücken und Tunnel werden linear überbrückt.
"""
import numpy as np

QUELLE = "BRouter (SRTM)"


def _interpoliere_luecken(werte):
    werte = werte.copy()
    ok = ~np.isnan(werte)
    if ok.sum() == 0:
        return werte
    idx = np.arange(len(werte))
    werte[~ok] = np.interp(idx[~ok], idx[ok], werte[ok])
    return werte


def anstieg(h, schwelle=3.0):
    """Höhenmeter bergauf mit Hysterese (kleine Wellen < schwelle zählen nicht)."""
    up, ref = 0.0, h[0]
    for v in h[1:]:
        if v > ref + schwelle:
            up += v - ref
            ref = v
        elif v < ref - schwelle:
            ref = v
    return up


def max_steigung(km, h, fenster_m=200):
    """Größte mittlere Steigung (%) über ein Fenster von fenster_m Metern."""
    if len(km) < 2:
        return 0.0
    schritt = max(1, int(round(fenster_m / ((km[1] - km[0]) * 1000 or 1))))
    if len(h) <= schritt:
        return 0.0
    dh = h[schritt:] - h[:-schritt]
    dx = (km[schritt:] - km[:-schritt]) * 1000
    return float(np.nanmax(np.abs(dh / np.where(dx > 0, dx, np.nan))) * 100)


def profil(coords, km, kunstbauten=(), abstand_m=50):
    """Höhenprofil entlang der Route im festen Abstand.

    coords: [[lon, lat, ele], ...] von BRouter, km: kumulierte km je coord
    kunstbauten: [(von_km, bis_km), ...] Brücken/Tunnel – dort wird linear überbrückt
    Rückgabe: (km_array, hoehen_array, quelle) oder None, wenn BRouter keine Höhen geliefert hat
    """
    if len(coords) < 2 or any(len(c) < 3 for c in coords):
        return None
    km = np.asarray(km, float)
    gesamt = km[-1]
    s = np.arange(0, gesamt, abstand_m / 1000)
    s = np.append(s, gesamt)
    h = np.interp(s, km, [float(c[2]) for c in coords])
    # Brücken und Tunnel: Gelände darunter/darüber ignorieren, linear überbrücken
    for von, bis in kunstbauten:
        h[(s > von - 0.025) & (s < bis + 0.025)] = np.nan
    h = _interpoliere_luecken(h)
    # glätten (150 m): SRTM-Raster ist grob, sonst zählen Rasterkanten als Anstieg
    if len(h) >= 3:
        h = np.convolve(np.pad(h, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    return s, h, QUELLE
