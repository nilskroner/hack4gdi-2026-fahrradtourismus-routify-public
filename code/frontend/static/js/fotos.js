// Routify – Straßenfotos (Mapillary) entlang der Strecke
// Lädt erst beim Aufklappen der Karte und nur Fotos, die auf dem Track liegen. Bilder kommen über unseren Server
// (/api/foto/…), der Browser verbindet sich also nicht mit Mapillary/Meta. Lizenz der Fotos: CC BY-SA 4.0.
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

let FOTOS_AN = false, fotoListe = [], fotoNr = 0;
const fotoEbene = L.layerGroup();
fetch("/api/config").then(r => r.json()).then(cfg => { FOTOS_AN = !!cfg.strassenfotos; }).catch(() => {});

function fotoKarte() {
  fotoEbene.clearLayers(); map.removeLayer(fotoEbene);
  if (!FOTOS_AN) return "";
  return `<details class="card" id="fotokarte" ontoggle="this.open ? fotosLaden() : fotoEbeneZeigen(false)">
    <summary><b>📷 Straßenfotos</b> <span class="src">lädt beim Öffnen</span></summary>
    <div id="fotoinhalt"></div>
  </details>`;
}

function fotoTag(km) {
  const s = (current.etappen || []).find(e => km >= e.von_km && km <= e.bis_km);
  return s && current.etappen.length > 1 ? `Tag ${s.nr} · ` : "";
}

async function fotosLaden() {
  const box = $("fotoinhalt");
  if (!box || !current) return;
  const variante = current;
  if (!variante._fotos) {
    box.innerHTML = `<div class="src"><span class="spinner"></span> Suche Fotos direkt auf deiner Strecke …</div>`;
    try {
      const r = await fetch("/api/fotos", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ geometrie: variante.geometrie, anzahl: 18 }) });
      const j = await r.json();
      if (!r.ok || (j.fehler && !(j.fotos || []).length)) throw new Error(j.fehler || "Server-Fehler");
      variante._fotos = j.fotos || [];
    } catch (e) {
      box.innerHTML = `<div class="empty">Straßenfotos sind gerade nicht verfügbar.</div><div class="src">${esc(e.message)}</div>`;
      return;
    }
  }
  if (current !== variante || !$("fotoinhalt")) return;  // inzwischen andere Variante gewählt
  fotoListe = variante._fotos;
  if (!fotoListe.length) { $("fotoinhalt").innerHTML = `<div class="empty">Für diese Strecke gibt es keine Fotos direkt auf dem Weg.</div>`; return; }
  $("fotoinhalt").innerHTML = `<div class="fotogrid">${fotoListe.map((f, i) => `
      <button class="foto" onclick="fotoZeigen(${i})" title="Groß anzeigen">
        <img loading="lazy" src="/api/foto/${esc(f.id)}" alt="Straßenfoto bei km ${f.km}">
        <span>${fotoTag(f.km)}km ${String(f.km).replace(".", ",")}</span></button>`).join("")}</div>
    <div class="src" style="margin-top:6px">${fotoListe.length} Fotos von Mapillary (CC BY-SA 4.0), aufgenommen von Freiwilligen. Antippen zum Vergrößern.</div>`;
  fotoEbeneZeigen(true);
}

function fotoEbeneZeigen(an) {
  fotoEbene.clearLayers();
  if (!an) { map.removeLayer(fotoEbene); return; }
  fotoListe.forEach((f, i) => L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "", html: `<div class="fotopin">📷</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) })
    .on("click", () => fotoZeigen(i)).addTo(fotoEbene));
  fotoEbene.addTo(map);
}

function fotoZeigen(i) {
  if (!fotoListe.length) return;
  fotoNr = (i + fotoListe.length) % fotoListe.length;
  const f = fotoListe[fotoNr];
  let m = $("fotoModal");
  if (!m) {
    m = document.createElement("div");
    m.id = "fotoModal"; m.className = "modal fotomodal";
    m.onclick = (e) => { if (e.target === m) fotoSchliessen(); };
    document.body.appendChild(m);
  }
  const datum = f.zeit ? new Date(f.zeit).toLocaleDateString("de-DE", { month: "long", year: "numeric" }) : "";
  m.innerHTML = `<div class="fotobox">
      <img src="/api/foto/${esc(f.id)}?gross=1" alt="Straßenfoto bei km ${f.km}">
      <button class="fotonav l" onclick="fotoZeigen(fotoNr - 1)" aria-label="Vorheriges Foto">‹</button>
      <button class="fotonav r" onclick="fotoZeigen(fotoNr + 1)" aria-label="Nächstes Foto">›</button>
      <button class="fotozu" onclick="fotoSchliessen()" aria-label="Schließen">✕</button>
      <div class="fotounten"><div><b>${fotoTag(f.km)}km ${String(f.km).replace(".", ",")}</b>${datum ? ` · aufgenommen ${datum}` : ""}</div>
        <span class="src">Foto: ${esc(f.fotograf || "unbekannt")} · Mapillary · CC BY-SA 4.0 ·
        <a href="https://www.mapillary.com/app/?pKey=${esc(f.id)}" target="_blank" rel="noopener">auf Mapillary ansehen ↗</a> · ${fotoNr + 1}/${fotoListe.length}</span></div>
    </div>`;
  m.hidden = false;
  map.panTo([f.lat, f.lon]);
}

function fotoSchliessen() { const m = $("fotoModal"); if (m) m.hidden = true; }
document.addEventListener("keydown", (e) => {
  const m = $("fotoModal");
  if (!m || m.hidden) return;
  if (e.key === "Escape") fotoSchliessen();
  else if (e.key === "ArrowLeft") fotoZeigen(fotoNr - 1);
  else if (e.key === "ArrowRight") fotoZeigen(fotoNr + 1);
});
