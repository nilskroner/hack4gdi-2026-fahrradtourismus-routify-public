"""Minimaler Decoder für Mapbox-Vector-Tiles (Protobuf), nur Punkt-Features – ohne Zusatzpaket."""


def _varint(b, i):
    n = s = 0
    while True:
        c = b[i]; i += 1
        n |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return n, i


def _felder(b):
    """(feldnummer, wert) eines Protobuf-Puffers; Längen-Felder als bytes."""
    i, ende = 0, len(b)
    while i < ende:
        k, i = _varint(b, i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            n, i = _varint(b, i); v = b[i:i + n]; i += n
        elif t == 1:
            v = b[i:i + 8]; i += 8
        elif t == 5:
            v = b[i:i + 4]; i += 4
        else:
            raise ValueError("unbekannter Wire-Typ")
        yield f, v


def _packed(b):
    i, out = 0, []
    while i < len(b):
        v, i = _varint(b, i); out.append(v)
    return out


def _zz(n):
    return (n >> 1) ^ -(n & 1)


def _wert(b):
    import struct
    for f, v in _felder(b):
        if f == 1: return v.decode("utf-8", "replace")
        if f == 2: return struct.unpack("<f", v)[0]
        if f == 3: return struct.unpack("<d", v)[0]
        if f in (4, 5): return v
        if f == 6: return _zz(v)
        if f == 7: return bool(v)


def punkte(daten, layer, z, x, y):
    """Punkt-Features einer Ebene als Dicts mit lon/lat und Attributen."""
    import math
    for f, lb in _felder(daten):
        if f != 3:
            continue
        name, keys, vals, feats, extent = None, [], [], [], 4096
        for g, v in _felder(lb):
            if g == 1: name = v.decode()
            elif g == 2: feats.append(v)
            elif g == 3: keys.append(v.decode())
            elif g == 4: vals.append(_wert(v))
            elif g == 5: extent = v
        if name != layer:
            continue
        n = 2 ** z
        for fb in feats:
            tags, geom, typ = [], [], 0
            for g, v in _felder(fb):
                if g == 2: tags = _packed(v)
                elif g == 3: typ = v
                elif g == 4: geom = _packed(v)
            if typ != 1 or len(geom) < 3:
                continue
            px, py = _zz(geom[1]), _zz(geom[2])  # erster Punkt reicht
            lon = (x + px / extent) / n * 360 - 180
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
            d = {keys[tags[k]]: vals[tags[k + 1]] for k in range(0, len(tags) - 1, 2)}
            d.update(lon=lon, lat=lat)
            yield d
