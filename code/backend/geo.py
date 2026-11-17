"""Geometrie-Helfer: Distanzen, Gitter-Index für Umkreissuchen, Linien-Hilfen."""
import math




def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class GridIndex:
    """Einfacher Gitter-Index (0,05° Zellen) für Umkreissuchen."""

    CELL = 0.05

    def __init__(self, items):
        self.cells = {}
        for it in items:
            self.cells.setdefault(self._key(it["lon"], it["lat"]), []).append(it)

    def _key(self, lon, lat):
        return (math.floor(lon / self.CELL), math.floor(lat / self.CELL))

    def near(self, lon, lat, radius_km):
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
        x0, y0 = self._key(lon - dlon, lat - dlat)
        x1, y1 = self._key(lon + dlon, lat + dlat)
        out = []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for it in self.cells.get((x, y), []):
                    d = haversine_km(lon, lat, it["lon"], it["lat"])
                    if d <= radius_km:
                        out.append((d, it))
        out.sort(key=lambda t: t[0])
        return out


def cumulative_km(coords):
    km = [0.0]
    for (x1, y1, *_), (x2, y2, *_) in zip(coords, coords[1:]):
        km.append(km[-1] + haversine_km(x1, y1, x2, y2))
    return km


def downsample(seq, n):
    if len(seq) <= n:
        return seq
    step = len(seq) / n
    return [seq[int(i * step)] for i in range(n)] + [seq[-1]]


def ascend(eles):
    up = 0.0
    for a, b in zip(eles, eles[1:]):
        if b > a:
            up += b - a
    return up


def peilung(lon1, lat1, lon2, lat2):
    """Fahrtrichtung in Grad (0 = Nord, 90 = Ost)."""
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def wind_relativ(fahrtrichtung, wind_aus, wind_kmh):
    """Gegen-/Rückenwind-Anteil (km/h, + = Gegenwind) und Bezeichnung. Windrichtung = woher der Wind kommt."""
    if fahrtrichtung is None or wind_aus is None or not wind_kmh:
        return None, None
    gegen = wind_kmh * math.cos(math.radians(wind_aus - fahrtrichtung))
    if wind_kmh < 8:
        return round(gegen), "kaum Wind"
    if gegen > wind_kmh * 0.5:
        return round(gegen), "Gegenwind"
    if gegen < -wind_kmh * 0.5:
        return round(gegen), "Rückenwind"
    return round(gegen), "Seitenwind"
