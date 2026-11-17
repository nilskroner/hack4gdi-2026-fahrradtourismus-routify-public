// Routify – Planung: Varianten auf der Karte, Marker, Höhenprofil, Seitenleiste
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// ---------- Ergebnis anzeigen
function showAlt(i, keepView = current !== null && data.alternativen.includes(current)) {
  current = data.alternativen[i];
  const color = COLORS[vIdx(i) % COLORS.length];

  layers.routes.clearLayers();
  // Erst die nicht gewählten Varianten, dann die gewählte obendrauf (mit weißem Rand)
  const order = data.alternativen.map((_, j) => j).filter(j => j !== i).concat(i);
  let bounds = null;
  order.forEach(j => {
    const a = data.alternativen[j], on = j === i, c = COLORS[vIdx(j) % COLORS.length];
    const tip = `Variante ${String.fromCharCode(65 + vIdx(j))} · ${a.laenge_km} km · ${a.anstieg_m} Hm${on ? "" : " – klicken zum Auswählen"}`;
    // Weißer Rand unter jeder Linie, damit sie sich von jeder Hintergrundkarte abhebt
    const eingefaerbt = on && colorMode !== "variante" && a.wege?.abschnitte?.length;
    L.polyline(a.geometrie, { color: eingefaerbt ? "#fff" : CASING[vIdx(j) % CASING.length], weight: on ? 11 : 7, opacity: on ? 1 : .8, interactive: false }).addTo(layers.routes);
    const line = L.polyline(a.geometrie, { color: c, weight: on ? 6 : 4, opacity: eingefaerbt ? 0 : (on ? 1 : .75) })
      .on("click", () => showAlt(j)).bindTooltip(tip, { sticky: true }).addTo(layers.routes);
    if (eingefaerbt) {
      const cats = colorMode === "wegtyp" ? WEGTYP : UNTERGRUND, key = colorMode === "wegtyp" ? "wt" : "ug";
      a.wege.abschnitte.forEach(ab => {
        const cat = cats[ab[key]] || { l: ab[key], c: "#999" };
        L.polyline(ab.pts, { color: cat.c, weight: 6, opacity: 1 })
          .bindTooltip(`${cat.ic || ""} ${cat.l} · ${ab.km} km`, { sticky: true }).addTo(layers.routes);
      });
    }
    if (!on) line.on("mouseover", () => line.setStyle({ opacity: 1, weight: 5 })).on("mouseout", () => line.setStyle({ opacity: .75, weight: 4 }));
    bounds = bounds ? bounds.extend(line.getBounds()) : line.getBounds();
  });
  if (!keepView) map.fitBounds(bounds, { padding: [30, 30] });

  drawMarkers(color);
  drawProfile(color);
  renderSidebar(i);
}

function popup(it, kat) {
  const k = KAT[kat];
  const wd = it.wikidata ? ` · <a target="_blank" href="https://www.wikidata.org/wiki/${esc(it.wikidata)}">${esc(it.wikidata)}</a>` : "";
  const osm = it.osm ? ` · <a target="_blank" href="https://www.openstreetmap.org/${esc(it.osm)}">${esc(it.osm)}</a>` : "";
  const web = it.web ? `<a target="_blank" href="${esc(it.web)}">Website</a>` : "";
  const art = it.detail && kat === "unterkunft" ? it.detail : (TYP[it.typ] || k.label);
  const kontakt = [it.adresse, it.telefon ? `Tel. ${it.telefon}` : ""].filter(Boolean).map(esc).join("<br>");
  return `<b>${k.ic} ${esc(it.name || "(ohne Namen)")}</b><br>${esc(art)}${it.dist_km != null ? ` · ${it.dist_km} km vom Etappenende` : ""}
          ${kontakt ? `<br>${kontakt}` : ""}${web ? `<br>${web}` : ""}
          <div class="src">Quelle: ${esc(it.quelle)}${osm}${wd}</div>`;
}

function drawMarkers(color) {
  ["stages", "unterkunft", "bahnhof", "rad"].forEach(l => layers[l].clearLayers());
  const o = data.orte[0];
  L.marker([o.lat, o.lon], { icon: L.divIcon({ className: "", html: `<div class="pin" style="background:${color};color:${pinText(color)}">S</div>`, iconSize: [22, 22] }) })
    .bindPopup(`<b>Start</b><br>${esc(o.label)}`).addTo(layers.stages);
  current.etappen.forEach(s => {
    const label = s.letzte ? "Z" : s.nr;
    L.marker([s.ende.lat, s.ende.lon], { icon: L.divIcon({ className: "", html: `<div class="pin" style="background:${color};color:${pinText(color)}">${label}</div>`, iconSize: [22, 22] }) })
      .bindPopup(s.letzte ? `<b>Ziel</b> · km ${s.bis_km}` : `<b>Ende Tag ${s.nr}</b> · km ${s.bis_km}`).addTo(layers.stages);
    (s.unterkuenfte || []).forEach((u, k) => {
      const sel = selection[s.nr] === k;
      L.circleMarker([u.lat, u.lon], { radius: sel ? 9 : 6, color: "#fff", weight: 2, fillColor: KAT.unterkunft.color, fillOpacity: sel ? 1 : .75 })
        .bindPopup(popup(u, "unterkunft") + (s.uebernachtung ? "" : `<br><button class="pickbtn" onclick="selection[${s.nr}]=${k}; uebernachten(${s.nr},${k})">🛏️ Hier übernachten (Tag ${s.nr})</button>`))
        .addTo(layers.unterkunft);
    });
  });
  (current.notausstiege || []).forEach(b => {
    const amEnde = current.etappen.some(s => s.bahnhof && s.bahnhof.id === b.id);
    L.circleMarker([b.lat, b.lon], { radius: amEnde ? 7 : 5, color: "#fff", weight: 1.5, fillColor: KAT.bahnhof.color, fillOpacity: .9 })
      .bindPopup(`<b>🚉 ${esc(b.name)}</b> · Notausstieg<br>${b.dist_km} km von der Route (bei km ${b.route_km})<br>${esc(b.verkehr.join(", "))}<div class="src">Quelle: ${esc(b.quelle)} · ${esc(b.id)}</div>`)
      .addTo(layers.bahnhof);
  });
  // Wunsch-POIs: eingeplante Stopps (groß) und Auswahl-Kandidaten
  layers.wunsch.clearLayers();
  wpListe().forEach(p => {
    const ic = p.typ === "nacht" ? "🛏️" : p.typ === "poi" ? (POI_ICON[p.kat] || "📍") : "📍";
    const txt = p.typ === "nacht" ? "Übernachtung – Etappe endet hier" : p.typ === "poi" ? "Zwischenstopp – die Route führt hier vorbei" : "Zwischenziel";
    L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", html: `<div class="pin poi on">${ic}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] }) })
      .bindPopup(poiPopup({ ...p, quelle: p.quelle || (p.typ === "ort" ? "Ortssuche (Photon/OSM)" : "") }, txt)).addTo(layers.wunsch);
  });
  (data.poi_auswahl || []).forEach(g => g.kandidaten.forEach((p, k) => {
    L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "", html: `<div class="pin poi">${g.icon}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] }) })
      .bindPopup(poiPopup(p, `bei km ${p.route_km} · ${p.dist_km} km von der Route`) + `<br><button class="pickbtn" onclick="viaWaehlen('${g.kategorie}',${k})">Route darüber führen</button>`)
      .addTo(layers.wunsch);
  }));
  current.rad_pois.forEach(p => {
    L.circleMarker([p.lat, p.lon], { radius: 4, color: KAT[p.kat].color, weight: 1, fillOpacity: .8 })
      .bindPopup(popup(p, p.kat) + `<div class="src">bei km ${p.route_km}</div>`).addTo(layers.rad);
  });
}

function drawProfile() {
  const i = data.alternativen.indexOf(current);
  const ds = data.alternativen.map((a, j) => {
    const c = CHART_COLORS[vIdx(j) % CHART_COLORS.length], on = j === i;
    return {
      label: `Variante ${String.fromCharCode(65 + vIdx(j))}`,
      data: a.hoehenprofil.map(([x, y]) => ({ x, y })),
      borderColor: on ? c : c + "99", backgroundColor: c + "26",
      borderWidth: on ? 2.5 : 1.3, fill: on, order: on ? 0 : 1,
      pointRadius: 0, tension: .2, altIdx: j,
    };
  });
  chart.data.datasets = ds;
  chart.options.scales.x.max = Math.max(...data.alternativen.map(a => a.laenge_km));
  // Höhenachse nach der gewählten Variante – sonst wird eine flache Tour neben einer bergigen zum Strich
  const eles = current.hoehenprofil.map(p => p[1]);
  const lo = Math.min(...eles), hi = Math.max(...eles), luft = Math.max(15, (hi - lo) * 0.15);
  chart.options.scales.y.min = Math.max(0, Math.floor((lo - luft) / 10) * 10);
  chart.options.scales.y.max = Math.ceil((hi + luft) / 10) * 10;
  $("profil").classList.remove("leer");
  chart.update();
  const quelle = current.hoehen_quelle || "BRouter (SRTM)";
  const link = quelle.includes("BKG") ? quelle.replace("BKG", '<a href="https://www.bkg.bund.de" target="_blank">BKG</a>') : esc(quelle);
  $("profLbl").innerHTML = `Höhenprofil · Variante ${String.fromCharCode(65 + vIdx(i))}: ${Math.round(Math.min(...eles))}–${Math.round(Math.max(...eles))} m`
    + `${current.max_steigung != null ? ` · max. Steigung ${current.max_steigung} %` : ""} · Quelle: ${link}`;
}

function renderSidebar(active) {
  const fmtDate = (iso, plus) => { const d = new Date(iso); d.setDate(d.getDate() + plus); return d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" }); };
  const p = data.params;
  const buchst = (j) => String.fromCharCode(65 + vIdx(j));

  // --- Route: Wegpunkte (bearbeitbar)
  const wps = wpListe();
  const pc = CHART_COLORS[vIdx(active) % CHART_COLORS.length];  // wie die Pins auf der Karte
  const pinListe = (t) => `<span class="pin klein" style="background:${pc};color:${pinText(pc)}">${t}</span>`;
  const wpIcon = (w) => w.typ === "nacht" ? "🛏️" : w.typ === "poi" ? (POI_ICON[w.kat] || "📍") : "📍";
  const wpArt = (w) => w.typ === "nacht" ? "Übernachtung" : w.typ === "poi" ? "Stopp" : "Zwischenziel";
  const route = `<div class="wps">
      <div class="wp fix"><span class="wpi">${pinListe("S")}</span><span class="wpn"><b>${esc(data.orte[0].label)}</b></span></div>
      ${wps.map((w, k) => `<div class="wp"><span class="wpi">${wpIcon(w)}</span>
        <span class="wpn" onclick="map.flyTo([${w.lat},${w.lon}],13)"><b>${esc(w.name)}</b><span class="src">${wpArt(w)}${w.detail ? " · " + esc(w.detail) : ""}</span></span>
        <span class="wpb">
          <button title="nach oben" ${k === 0 ? "disabled" : ""} onclick="wpVerschieben(${k},-1)">↑</button>
          <button title="nach unten" ${k === wps.length - 1 ? "disabled" : ""} onclick="wpVerschieben(${k},1)">↓</button>
          <button title="entfernen" onclick="wpEntfernen(${k})">✕</button></span></div>`).join("")}
      <div class="wp fix"><span class="wpi">${pinListe("Z")}</span><span class="wpn"><b>${esc(data.orte.at(-1).label)}</b></span></div>
      <div class="wpadd">
        <input type="text" id="wpNeu" placeholder="Zwischenziel hinzufügen" onkeydown="if(event.key==='Enter')wpHinzu()">
        <button onclick="wpHinzu()" title="Zwischenziel hinzufügen">＋</button>
        <button onclick="wpTauschen()" title="Start und Ziel tauschen">⇅</button>
      </div>
    </div>`;

  // --- Kennzahlen + Einstellungen in einer Zeile
  const kpis = `<div class="kpis">
      <div><b>${Math.round(current.laenge_km)}</b><span>km</span></div>
      <div><b>${current.etappen.length}</b><span>${current.etappen.length > 1 ? "Tage" : "Tag"}</span></div>
      <div><b>${current.anstieg_m}</b><span>Hm</span></div>
      <div><b>${current.max_steigung ?? "–"}${current.max_steigung != null ? " %" : ""}</b><span>max. Steigung</span></div>
      <div title="geschätzt aus Tempo (Zielgruppe/Rad) und Höhenmetern, ohne Pausen"><b>${fahrzeitKurz(current.etappen.length > 1 ? current.fahrzeit_h / current.etappen.length : current.fahrzeit_h)}</b><span>${current.etappen.length > 1 ? "Fahrzeit/Tag" : "Fahrzeit"}</span></div>
    </div>`;
  const einst = [
    data.radweg ? `🛤️ ${esc(data.radweg.name)}` : null,
    { normal: null, familie: "Familie", senioren: "Senioren", sportlich: "Sportlich" }[p.zielgruppe],
    p.fahrrad && p.fahrrad !== "normal" ? RAEDER[p.fahrrad] : null,
    (p.unterkunft_typ || []).length ? p.unterkunft_typ.map(u => TYP[u] || u).join("/") : null,
    ...(p.vorlieben || []).map(v => VORLIEBE_LABEL[v] || v),
    `ab ${fmtDate(data.startdatum, 0)}`,
    `Profil ${esc(current.profil)}`,
  ].filter(Boolean).join(" · ");
  const nNot = (current.notausstiege || []).length;
  const tour = `<section class="card tourcard">
      <div class="tourbtns">
        <button class="dl zwei" onclick="tourSpeichern()" title="Tour in deinem Konto speichern">☆ Speichern</button>
        <button class="dl" onclick="gpxExport()" title="Gewählte Variante mit Etappen und POIs als GPX-Datei herunterladen (für Garmin, Komoot, Wahoo …)">⤓ GPX</button>
      </div>
      ${route}
      ${kpis}
      <div class="einst">${einst}</div>
      ${data.hinweise.map(h => `<div class="hint">${esc(h)}</div>`).join("")}
      ${data.nur_variante != null ? `<button class="link" onclick="alleVarianten()">↺ Andere Varianten wieder anzeigen</button><br>` : ""}

    </section>`;

  // --- Auswahl (Wunsch-Stopps) – nur wenn offen
  const auswahl = (data.poi_auswahl || []).map(g => `
    <section class="card accent">
      <h3>${g.icon} ${esc(g.label)} unterwegs wählen</h3>
      ${g.kandidaten.map((q, k) => `
        <div class="poiopt" onclick="viaWaehlen('${g.kategorie}',${k})" onmouseenter="map.panTo([${q.lat},${q.lon}])">
          <span><b>${esc(q.name || "(ohne Namen)")}</b>${q.detail ? ` · ${esc(q.detail)}` : ""}${q.notfall ? " · Notaufnahme" : ""}<br>
          <span class="src">${esc(q.ort || "")} · km ${q.route_km} · ${q.dist_km} km Umweg</span></span>
          <span class="chip ex">Wählen</span>
        </div>`).join("")}
    </section>`).join("");

  // --- Varianten: kompakt
  const alts = data.alternativen.length > 1 ? `<div class="alts">${data.alternativen.map((a, j) => `
    <button class="alt ${j === active ? "on" : ""}" style="--c:${CHART_COLORS[vIdx(j) % CHART_COLORS.length]}" onclick="showAlt(${j})">
      <b><span class="dot"></span>${esc(variantenName(a, j))}</b>
      <small>${Math.round(a.laenge_km)} km · ${a.anstieg_m} Hm · ${fahrzeitKurz(a.fahrzeit_h)}</small>
      ${a.titel && a.wegpunkte?.length ? `<small class="ueb">${a.wegpunkte.filter(w => w.name !== "Wegpunkt").map(w => esc(w.name)).join(" · ")}</small>` : ""}
    </button>`).join("")}</div>` : "";

  // --- Etappen: das Wichtigste sichtbar, Details aufklappbar
  const stages = current.etappen.map(s => {
    const w = s.wetter;
    const wetter = !w ? "" : w.hinweis ? `<span class="src">${esc(w.hinweis)}</span>`
      : `${esc(WETTER[w.lage] || "")} ${w.t_min}–${w.t_max} °C${w.regen_mm ? ` · ${w.regen_mm} mm` : ""} · Wind ${w.wind_kmh} km/h ${w.wind_richtung != null ? ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][Math.round(w.wind_richtung / 45) % 8] : ""}${w.wind_relativ && w.wind_relativ !== "kaum Wind" ? ` · <b class="${w.wind_relativ === "Gegenwind" ? "warn" : ""}">${w.wind_relativ}</b>` : ""}`;
    let nacht = "";
    if (s.letzte) nacht = `<div class="row"><span class="ic">🏁</span><span>Ankunft in ${esc(data.orte.at(-1).label)}</span></div>`;
    else if (s.uebernachtung) nacht = `<div class="row"><span class="ic">🛏️</span><span style="flex:1"><b>${esc(s.uebernachtung.name)}</b>${s.uebernachtung.adresse ? `<span class="src" style="display:block">${esc(s.uebernachtung.adresse)}</span>` : ""}</span>
        <button class="link" onclick="event.stopPropagation(); nachtEntfernen('${esc(s.uebernachtung.name).replace(/'/g, "\\'")}')">ändern</button></div>`;
    else if (s.unterkuenfte?.length) nacht = `<div class="row"><span class="ic">🛏️</span><span style="flex:1">
        ${s.unterkuenfte.map((u, k) => `
          <label class="opt ${selection[s.nr] === k ? "sel" : ""}" onclick="event.stopPropagation()">
            <input type="radio" name="u${s.nr}" ${selection[s.nr] === k ? "checked" : ""} onchange="pick(${s.nr},${k})">
            <span><b>${esc(u.name || "(ohne Namen)")}</b>
            <span class="src">${esc(TYP[u.typ] || u.typ)} · ${u.dist_km} km</span></span>
          </label>
          ${selection[s.nr] === k ? `<button class="pickbtn" style="margin:2px 0 6px 28px" onclick="event.stopPropagation(); uebernachten(${s.nr},${k})">Hier übernachten – Route anpassen</button>` : ""}`).join("")}
      </span></div>`;
    else nacht = `<div class="row"><span class="ic">🛏️</span><span class="empty">Keine Unterkunft im Umkreis von 8 km</span></div>`;

    const wg = s.wege, warn = [];
    if (wg?.wegtyp?.hauptstrasse >= 500) warn.push(`⚠️ ${(wg.wegtyp.hauptstrasse / 1000).toFixed(1)} km Hauptstraße`);
    if (wg?.untergrund?.unbefestigt >= 500) warn.push(`${(wg.untergrund.unbefestigt / 1000).toFixed(1)} km unbefestigt`);
    if (wg?.untergrund?.pflaster >= 1000) warn.push(`${(wg.untergrund.pflaster / 1000).toFixed(1)} km Pflaster`);
    if (s.max_steigung >= 8) warn.push(`⚠️ bis ${s.max_steigung} % Steigung`);
    const radAnteil = wg ? Math.round((wg.wegtyp.radweg || 0) / (Object.values(wg.wegtyp).reduce((a, b) => a + b, 0) || 1) * 100) : null;
    const na = s.notausstiege || [];
    const details = `<details onclick="event.stopPropagation()"><summary>Weg & Details${warn.length ? ` · <span class="warn">${warn.length} Hinweis${warn.length > 1 ? "e" : ""}</span>` : ""}</summary>
        ${wg ? `${bar(wg.wegtyp, WEGTYP, "sm")}${bar(wg.untergrund, UNTERGRUND, "sm")}<div class="src">${radAnteil} % Radweg · max. ${s.max_steigung ?? "?"} % Steigung</div>` : ""}
        ${warn.map(x => `<div class="src">${x}</div>`).join("")}
        ${bahnZeigen ? (na.length ? `<div class="src" style="margin-top:4px">🚉 Notausstiege:</div>${na.map(b => `<div class="na" onclick="map.flyTo([${b.lat},${b.lon}],14)">km ${b.route_km} · ${esc(b.name)} · ${b.dist_km} km</div>`).join("")}` : `<div class="src">🚉 Kein Bahnhof ≤ 5 km</div>`) : ""}
      </details>`;
    const offen = etappeOffen.has(s.nr);
    const kurzWetter = w && !w.hinweis ? `${(WETTER[w.lage] || "").split(" ")[0]} ${w.t_max}°` : "";
    const kurzNacht = s.uebernachtung ? "🛏️ ✓" : "";
    return `<section class="stage ${offen ? "open" : ""}">
      <div class="top" onclick="etappeUmschalten(${s.nr})">
        <b><span class="chev">${offen ? "▾" : "▸"}</span> Tag ${s.nr} <span class="dat">${fmtDate(data.startdatum, s.nr - 1)}</span></b>
        <span class="meta">${kurzWetter} · ${Math.round(s.laenge_km)} km · ${s.anstieg_m ?? "?"} Hm · ${fahrzeitText(s.fahrzeit_h)} ${kurzNacht}</span></div>
      ${offen ? `${wetter ? `<div class="wett">${wetter}</div>` : ""}${nacht}${details}
        <button class="link" onclick="event.stopPropagation(); map.flyTo([${s.ende.lat},${s.ende.lon}], 12)">Auf der Karte zeigen</button>` : ""}
    </section>`;
  }).join("");

  // --- Wege & Untergrund: zugeklappt, Kurzfassung in der Überschrift
  const wgA = current.wege;
  const anteil = (d, k) => d ? Math.round((d[k] || 0) / (Object.values(d).reduce((a, b) => a + b, 0) || 1) * 100) : 0;
  const wege = wgA ? `<details class="card" ${colorMode !== "variante" ? "open" : ""}>
      <summary><b>Wege & Untergrund</b> <span class="src">${anteil(wgA.wegtyp, "radweg")} % Radweg · ${anteil(wgA.untergrund, "asphalt")} % Asphalt</span></summary>
      ${data.alternativen.map((a, j) => a.wege ? `
        <div class="wrow ${j === active ? "on" : ""}" style="--c:${CHART_COLORS[vIdx(j) % CHART_COLORS.length]}" onclick="showAlt(${j}, true)">
          <span class="wl">${buchst(j)}</span>
          <div class="bars">${bar(a.wege.wegtyp, WEGTYP)}${bar(a.wege.untergrund, UNTERGRUND)}</div>
        </div>` : "").join("")}
      <div class="wleg">
        <div class="wcol"><b>Wegtyp</b>${barLegend(wgA.wegtyp, WEGTYP)}</div>
        <div class="wcol"><b>Untergrund</b>${barLegend(wgA.untergrund, UNTERGRUND)}</div>
      </div>
      <div class="seg">
        <button class="${colorMode === "variante" ? "on" : ""}" onclick="setColorMode('variante')">Karte: Variante</button>
        <button class="${colorMode === "wegtyp" ? "on" : ""}" onclick="setColorMode('wegtyp')">Wegtyp</button>
        <button class="${colorMode === "untergrund" ? "on" : ""}" onclick="setColorMode('untergrund')">Untergrund</button>
      </div>
    </details>` : "";

  // --- Wettersuche: bester Tag im Zeitraum, andere Tage wählbar
  const ww = data.wetter_wahl;
  const wtag = (iso) => new Date(iso).toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
  const wetterKarte = !ww ? "" : (() => {
    const maxR = Math.max(1, ...ww.kandidaten.map(k => k.regen_mm));
    const gew = ww.kandidaten.find(k => k.gewaehlt) || ww.kandidaten.find(k => k.bester);
    return `<section class="card accent">
      <h3>🌤️ ${gew.bester ? "Bester Tag" : "Gewählter Tag"}: ${wtag(gew.start)}${gew.trocken ? " · trocken" : ` · ${gew.regen_mm} mm Regen`}</h3>
      <div class="src" style="margin:-4px 0 8px">Wetter der nächsten ${ww.zeitraum_tage} Tage entlang der Route (${{ trocken: "möglichst trocken", rueckenwind: "Rückenwind & trocken" }[ww.kriterium] || "gutes Wetter"}) · ${esc(ww.quelle)}</div>
      <div class="wtage">${ww.kandidaten.map(k => `
        <button class="wtag ${k.gewaehlt ? "on" : ""}" onclick="wetterTag('${k.start}')" title="Regen ${k.regen_mm} mm · ${k.regen_wahrsch} % · bis ${k.t_max} °C · Wind ${k.wind_kmh} km/h">
          <span class="wd">${wtag(k.start).split(",")[0]}</span>
          <span class="wbar"><span style="height:${Math.max(4, k.regen_mm / maxR * 100)}%" class="${k.trocken ? "dry" : ""}"></span></span>
          <span class="wmm">${k.trocken ? "☀️" : k.regen_mm + " mm"}</span>
          <span class="wt">${k.t_max}°</span>
          ${k.bester ? '<span class="wstar">★</span>' : ""}
        </button>`).join("")}</div>
    </section>`;
  })();
  const alleOffen = current.etappen.every(s => etappeOffen.has(s.nr));
  const etappenKopf = `<div class="etkopf"><h3>Etappen</h3>${current.etappen.length > 1
    ? `<button class="link" onclick="alleEtappen(${!alleOffen})">${alleOffen ? "alle einklappen" : "alle ausklappen"}</button>` : ""}</div>`;
  const exportBtn = `<button class="export" onclick="gpxExport()">
      <span class="ex-ic">⤓</span>
      <span><b>Route als GPX herunterladen</b>
      <small>${current.etappen.length > 1 ? `${current.etappen.length} Etappen` : "Tagestour"} · mit Unterkünften & POIs · für Garmin, Komoot, Wahoo</small></span>
    </button>`;
  kartenVarianten(active);
  $("result").innerHTML = `${tour}${pruefKarte()}${wetterKarte}${auswahl}${alts ? `<h3>Varianten</h3>${alts}` : ""}${etappenKopf}${stages}${wege}${fotoKarte()}${linkedDataKarte()}${exportBtn}`;
  pruefungLaden();
  $("input").placeholder = "Änderung? z. B. „lieber 3 Tage“, „mit Campingplatz“";
}

// Handy: Variantenwahl direkt über der Karte (am Laptop ausgeblendet, dort stehen die Varianten in der Planung)
function kartenVarianten(active) {
  const el = $("kartenVarianten");
  if (!el) return;
  el.innerHTML = data && data.alternativen.length > 1 ? data.alternativen.map((a, j) => `
    <button class="${j === active ? "on" : ""}" style="--c:${CHART_COLORS[vIdx(j) % CHART_COLORS.length]}" onclick="showAlt(${j})">
      <span class="dot"></span><b>${esc(variantenName(a, j))}</b> ${Math.round(a.laenge_km)} km</button>`).join("") : "";
}
