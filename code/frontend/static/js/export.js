// Routify – Export: GPX-Datei der gewählten Variante
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// ---------- GPX-Export: gewählte Variante, ein Track je Tag, POIs als Wegpunkte
const xml = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]));
const GPX_SYMBOL = {  // Symbolnamen, die Garmin & Co. kennen
  start: "Flag, Green", ziel: "Flag, Red", etappe: "Flag, Blue", nacht: "Lodging", unterkunft: "Lodging",
  fahrradladen: "Bike Trail", reparatur: "Bike Trail", verleih: "Bike Trail", bahnhof: "Ground Transportation",
  ort: "City (Small)", poi: "Pin, Green", wegpunkt: "Pin, Green",
};

function gpxExport() {
  if (!data || !current) return;
  const p = data.params, a = current;
  // Höhe je Trackpunkt aus dem Höhenprofil (km -> m) interpolieren
  const prof = a.hoehenprofil || [];
  const hoehe = (km) => {
    if (!prof.length) return null;
    let i = prof.findIndex(([k]) => k >= km);
    if (i <= 0) return prof[Math.max(0, i)][1];
    const [k0, h0] = prof[i - 1], [k1, h1] = prof[i];
    return h0 + (h1 - h0) * ((km - k0) / ((k1 - k0) || 1));
  };
  const dist = (x, y) => { const r = Math.PI / 180, dLat = (y[0] - x[0]) * r, dLon = (y[1] - x[1]) * r;
    const q = Math.sin(dLat / 2) ** 2 + Math.cos(x[0] * r) * Math.cos(y[0] * r) * Math.sin(dLon / 2) ** 2; return 12742 * Math.asin(Math.sqrt(q)); };
  let km = 0;
  const punkte = a.geometrie.map((pt, i) => { if (i) km += dist(a.geometrie[i - 1], pt); return { lat: pt[0], lon: pt[1], km }; });
  const faktor = a.laenge_km / (km || 1);  // auf Routenlänge normieren
  punkte.forEach(q => q.km *= faktor);

  const tagDatum = (n) => { const d = new Date(data.startdatum); d.setDate(d.getDate() + n - 1); return d.toISOString().slice(0, 10); };
  const trkpt = (q) => { const h = hoehe(q.km); return `<trkpt lat="${q.lat.toFixed(6)}" lon="${q.lon.toFixed(6)}">${h != null ? `<ele>${h.toFixed(1)}</ele>` : ""}</trkpt>`; };
  const tracks = a.etappen.map(s => {
    const teil = punkte.filter(q => q.km >= s.von_km - 0.05 && q.km <= s.bis_km + 0.05);
    return `  <trk>
    <name>${xml(`Tag ${s.nr} (${tagDatum(s.nr)}): ${Math.round(s.laenge_km)} km, ${s.anstieg_m ?? "?"} Hm`)}</name>
    <desc>${xml(`km ${s.von_km}–${s.bis_km}${s.max_steigung != null ? ` · max. ${s.max_steigung} % Steigung` : ""}${s.uebernachtung ? ` · Übernachtung: ${s.uebernachtung.name}` : ""}`)}</desc>
    <type>cycling</type>
    <trkseg>${teil.map(trkpt).join("")}</trkseg>
  </trk>`;
  }).join("\n");

  // Wegpunkte (doppelte Orte zusammenfassen)
  const wpts = [], gesehen = new Set();
  const wpt = (lat, lon, name, sym, desc, typ, link) => {
    const key = `${(+lat).toFixed(4)},${(+lon).toFixed(4)},${name}`;
    if (lat == null || lon == null || gesehen.has(key)) return;
    gesehen.add(key);
    wpts.push(`  <wpt lat="${(+lat).toFixed(6)}" lon="${(+lon).toFixed(6)}"><name>${xml(name)}</name>${desc ? `<desc>${xml(desc)}</desc>` : ""}` +
              `${link ? `<link href="${xml(link)}"/>` : ""}<sym>${xml(sym)}</sym><type>${xml(typ)}</type></wpt>`);
  };
  wpt(data.orte[0].lat, data.orte[0].lon, `Start: ${data.orte[0].label}`, GPX_SYMBOL.start, "", "Start");
  wpListe().forEach(w => wpt(w.lat, w.lon, w.name, GPX_SYMBOL[w.typ === "nacht" ? "nacht" : w.kat] || GPX_SYMBOL[w.typ] || GPX_SYMBOL.poi,
    [w.typ === "nacht" ? "Übernachtung" : w.typ === "poi" ? "Zwischenstopp" : "Zwischenziel", w.detail, w.adresse || w.ort].filter(Boolean).join(" · "),
    w.typ === "nacht" ? "Übernachtung" : "Zwischenstopp", w.web));
  a.etappen.forEach(s => {
    if (!s.letzte) wpt(s.ende.lat, s.ende.lon, `Ende Tag ${s.nr}`, GPX_SYMBOL.etappe, `km ${s.bis_km}`, "Etappenende");
    if (s.uebernachtung) return;
    (s.unterkuenfte || []).forEach((u, k) => {
      if (selection[s.nr] != null && selection[s.nr] !== k) return;  // gewählte Unterkunft, sonst alle Vorschläge
      wpt(u.lat, u.lon, u.name || "Unterkunft", GPX_SYMBOL.unterkunft,
        [`Tag ${s.nr}`, u.detail || TYP[u.typ] || u.typ, u.adresse || u.ort,
         u.telefon ? `Tel. ${u.telefon}` : "", u.quelle].filter(Boolean).join(" · "), "Unterkunft", u.web);
    });
  });
  const z = data.orte.at(-1);
  wpt(z.lat, z.lon, `Ziel: ${z.label}`, GPX_SYMBOL.ziel, "", "Ziel");
  (a.rad_pois || []).forEach(q => wpt(q.lat, q.lon, q.name || KAT[q.kat]?.label || "Fahrrad", GPX_SYMBOL[q.kat] || GPX_SYMBOL.poi,
    [KAT[q.kat]?.label, `bei km ${q.route_km}`, q.quelle].filter(Boolean).join(" · "), KAT[q.kat]?.label || "Fahrrad", q.web));
  (data.poi_auswahl || []).forEach(g => g.kandidaten.forEach(q => wpt(q.lat, q.lon, q.name || g.label, GPX_SYMBOL[g.kategorie] || GPX_SYMBOL.poi,
    [`Vorschlag ${g.label}`, q.detail, `bei km ${q.route_km}`, q.quelle].filter(Boolean).join(" · "), g.label, q.web)));
  if (bahnZeigen) (a.notausstiege || []).forEach(b => wpt(b.lat, b.lon, b.name, GPX_SYMBOL.bahnhof,
    `Notausstieg · ${b.dist_km} km von der Route (km ${b.route_km}) · ${b.quelle}`, "Bahnhof"));

  const titel = `Routify: ${data.orte[0].label.split(",")[0]} → ${z.label.split(",")[0]}`;
  const gpx = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Routify (hack4GDI 2026)" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
  <metadata>
    <name>${xml(titel)}</name>
    <desc>${xml(`${a.laenge_km} km · ${a.etappen.length} Tag(e) · ${a.anstieg_m} Hm · Profil ${a.profil} · ab ${data.startdatum}`)}</desc>
    <copyright author="${xml("OpenStreetMap-Mitwirkende (ODbL), BKG (POI-Open dl-de/by-2-0), Höhen: SRTM via BRouter")}"/>
    <time>${new Date().toISOString()}</time>
  </metadata>
${wpts.join("\n")}
${tracks}
</gpx>
`;
  const datei = `routify_${titel.replace(/^Routify: /, "").replace(/[^A-Za-z0-9ÄÖÜäöüß→ -]/g, "").replace(/\s*→\s*/, "-").replace(/\s+/g, "_")}_${data.startdatum}.gpx`;
  const url = URL.createObjectURL(new Blob([gpx], { type: "application/gpx+xml" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: datei });
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  addMsg(`⤓ GPX exportiert: <b>${esc(datei)}</b> · ${a.etappen.length} Track${a.etappen.length > 1 ? "s" : ""} (je Tag), ${wpts.length} Wegpunkte`);
}

function pick(nr, k) {
  selection[nr] = k;
  const i = data.alternativen.indexOf(current);
  drawMarkers(COLORS[vIdx(i) % COLORS.length]);
  renderSidebar(i);
}
