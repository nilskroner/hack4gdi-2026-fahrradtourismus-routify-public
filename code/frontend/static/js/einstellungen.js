// Routify – Einstellungen (Formular, ohne Sprachmodell)
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// ---------- Expertenmodus: alle Einstellungen direkt bearbeiten (ohne LLM)
const ZIELGRUPPEN = { normal: "Normal", familie: "Familie mit Kindern", senioren: "Senioren", sportlich: "Sportlich" };
const RAEDER = { normal: "Trekking-/Stadtrad", ebike: "E-Bike", gravel: "Gravelbike", rennrad: "Rennrad", mtb: "Mountainbike" };
const PROFILE_WAHL = { "": "automatisch", trekking: "trekking – ausgewogen", safety: "safety – sicher, wenig Verkehr",
  fastbike: "fastbike – schnell, Straße", gravel: "gravel – Schotter ok", mtb: "mtb – Gelände", shortest: "shortest – kürzester Weg" };
const opt = (obj, wert) => Object.entries(obj).map(([k, l]) => `<option value="${k}" ${k === (wert ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("");

let expertAn = false;
try { expertAn = localStorage.getItem("routify-expert") === "1"; } catch (e) {}

function renderExpert() {
  const box = $("expert");
  box.hidden = !expertAn;
  $("expertToggle").checked = expertAn;
  if (!expertAn) return;
  const p = kontext || {};
  const unterk = p.unterkunft_typ || [];
  const wunsch = new Set((p.poi_wuensche || []).map(w => w.kategorie));
  box.innerHTML = `<h4>⚙️ Einstellungen</h4>
    <div class="fgrid">
      <label>Start<input type="text" id="x_start" value="${esc(p.start || "")}" placeholder="z. B. Mainz"></label>
      <label>Ziel<input type="text" id="x_ziel" value="${esc(p.ziel || "")}" placeholder="z. B. Koblenz"></label>
      <label class="full">Zwischenziele (mit Komma getrennt)<input type="text" id="x_zw" value="${esc((p.zwischenziele || []).join(", "))}" placeholder="optional"></label>
      <label>Tage<input type="number" id="x_tage" min="1" max="30" value="${p.tage ?? ""}" placeholder="automatisch"></label>
      <label>km pro Tag<input type="number" id="x_km" min="10" max="300" step="5" value="${p.km_pro_tag ?? ""}" placeholder="automatisch"></label>
      <label>Zielgruppe<select id="x_gruppe">${opt(ZIELGRUPPEN, p.zielgruppe || "normal")}</select></label>
      <label>Fahrrad<select id="x_rad">${opt(RAEDER, p.fahrrad || "normal")}</select></label>
      <label>Routing-Profil (BRouter)<select id="x_profil">${opt(PROFILE_WAHL, p.profil || "")}</select></label>
      <label>Start am<input type="date" id="x_datum" value="${esc(p.startdatum || "")}"></label>
      <label class="full">Unterkunft<span class="checks">
        ${Object.entries({ hotel: "Hotel", guest_house: "Pension", hostel: "Hostel/Jugendherberge", camp_site: "Camping" }).map(([k, l]) =>
          `<label><input type="checkbox" name="x_unterk" value="${k}" ${unterk.includes(k) ? "checked" : ""}>${l}</label>`).join("")}</span></label>
      <label class="full">Stopps unterwegs (Auswahl entlang der Route)<span class="checks">
        ${Object.keys(POI_ICON).map(k => `<label><input type="checkbox" name="x_poi" value="${k}" ${wunsch.has(k) ? "checked" : ""}>${POI_ICON[k]} ${k[0].toUpperCase() + k.slice(1)}</label>`).join("")}</span></label>
      <label class="full"><span class="checks"><label><input type="checkbox" id="x_bahn" ${p.bahnhoefe_zeigen ? "checked" : ""}>🚉 Notausstiege (Bahnhöfe ≤ 5 km) anzeigen</label></span></label>
    </div>
    <button class="go" id="x_go">Neu planen</button>
    <div class="src" style="margin-top:6px">Plant direkt mit diesen Werten, ohne Sprachmodell. Änderungen im Chat aktualisieren das Formular.</div>`;
  $("x_go").onclick = expertPlanen;
  box.querySelectorAll("input[type=text], input[type=number]").forEach(i => i.onkeydown = (e) => { if (e.key === "Enter") expertPlanen(); });
}

function expertPlanen() {
  const v = (id) => $(id).value.trim();
  const zahl = (id) => (v(id) ? Number(v(id)) : null);
  if (!v("x_start") || !v("x_ziel")) { addMsg("Bitte in den Einstellungen Start und Ziel angeben.", "err"); return; }
  const alt = kontext || {};
  const poi = [...document.querySelectorAll('input[name="x_poi"]:checked')].map(i => i.value);
  const params = {
    start: v("x_start"), ziel: v("x_ziel"),
    zwischenziele: v("x_zw") ? v("x_zw").split(",").map(x => x.trim()).filter(Boolean) : [],
    tage: zahl("x_tage"), km_pro_tag: zahl("x_km"),
    zielgruppe: $("x_gruppe").value, fahrrad: $("x_rad").value, profil: $("x_profil").value || null,
    startdatum: v("x_datum") || null,
    unterkunft_typ: [...document.querySelectorAll('input[name="x_unterk"]:checked')].map(i => i.value),
    // vorhandene Wünsche (auch konkrete Namen) behalten, neue Kategorien ergänzen
    poi_wuensche: [...(alt.poi_wuensche || []).filter(w => poi.includes(w.kategorie)),
                   ...poi.filter(k => !(alt.poi_wuensche || []).some(w => w.kategorie === k)).map(k => ({ kategorie: k, name: null }))],
    bahnhoefe_zeigen: $("x_bahn").checked,
    wuensche: alt.wuensche || [],
  };
  const gleicheStrecke = params.start === alt.start && params.ziel === alt.ziel;
  params.via_pois = gleicheStrecke ? (alt.via_pois || []).filter(x => poi.includes(x.kat)) : [];
  const diff = aenderungen(alt, params);
  send(`⚙️ Einstellungen${diff.length && kontext ? ": " + diff.map(d => d.replace(/<[^>]+>/g, "")).join(" · ") : ""}`, params);
}

$("expertToggle").onchange = (e) => {
  expertAn = e.target.checked;
  try { localStorage.setItem("routify-expert", expertAn ? "1" : "0"); } catch (err) {}
  renderExpert();
  if (expertAn) $("planscroll").scrollTop = 0;
};
renderExpert();
