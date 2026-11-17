// Routify – Chat: Nachrichten, Anfragen an /api/plan, Rückfragen
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// ---------- Chat
function addMsg(html, cls = "bot") {
  const d = document.createElement("div");
  d.className = "msg " + cls; d.innerHTML = html;
  $("chat").appendChild(d); $("scroll").scrollTop = 1e9;
  return d;
}

let lastText = "", pendingOptions = [], kontext = null;

const FELD_LABEL = { start: "Start", ziel: "Ziel", tage: "Tage", km_pro_tag: "km/Tag", zielgruppe: "Zielgruppe",
  fahrrad: "Fahrrad", unterkunft_typ: "Unterkunft", zwischenziele: "Zwischenziele", startdatum: "Start am", poi_wuensche: "Stopps", bahnhoefe_zeigen: "Notausstiege", profil: "Routing-Profil",
  vorlieben: "Vorlieben", rundtour: "Rundtour", laenge_km: "Länge" };

function zeigeWert(k, v) {
  if (typeof v === "boolean") return v ? "an" : "aus";
  if (v == null || (Array.isArray(v) && !v.length)) return "–";
  if (k === "unterkunft_typ") return v.map(u => TYP[u] || u).join(", ");
  if (k === "vorlieben") return v.map(x => VORLIEBE_LABEL[x] || x).join(", ");
  if (k === "poi_wuensche") return v.map(w => `${POI_ICON[w.kategorie] || ""} ${w.name || w.kategorie}`).join(", ");
  return Array.isArray(v) ? v.join(", ") : String(v);
}

function aenderungen(alt, neu) {
  if (!alt) return [];
  return Object.keys(FELD_LABEL).filter(k => JSON.stringify(alt[k] ?? null) !== JSON.stringify(neu[k] ?? null)
      && !((alt[k] == null || (Array.isArray(alt[k]) && !alt[k].length)) && (neu[k] == null || (Array.isArray(neu[k]) && !neu[k].length))))
    .map(k => `${FELD_LABEL[k]}: ${esc(zeigeWert(k, alt[k]))} → <b>${esc(zeigeWert(k, neu[k]))}</b>`);
}

async function send(text, params = null) {
  if (!text.trim()) return;
  addMsg(esc(text), "user");
  $("input").value = ""; $("input").style.height = "";
  $("send").disabled = true;
  if (!params) lastText = text;
  const vorher = params ? null : kontext;  // Nachricht als Änderung der aktuellen Planung verstehen
  const wait = addMsg(`<span class="spinner"></span>${vorher ? "Passe die Planung an" : params ? "Plane neu" : "Verstehe die Anfrage"} …`);
  const t0 = performance.now();
  try {
    const r = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: params ? lastText : text, params, vorher }) });
    const j = await r.json();
    wait.remove();
    if (!r.ok && !j.fehler && !j.rueckfrage) { addMsg("Die Planung hat nicht geklappt (Server-Fehler). Bitte nochmal versuchen.", "err"); return; }
    if (j.fehler) { addMsg(esc(j.fehler), "err"); return; }
    const diff = aenderungen(kontext, j.params || {});
    if (j.params) { kontext = j.params; renderExpert(); }
    if (j.rueckfrage) {
      pendingOptions = j.optionen || [];
      const btns = pendingOptions.map((o, k) => `<span class="chip ex" onclick="chooseOption(${k})">${esc(o.label)}</span>`).join("");
      addMsg(`${esc(j.rueckfrage)}${btns ? `<div class="chips" style="margin-top:8px">${btns}</div>` : ""}`);
      return;
    }
    const gleicheStrecke = !!(data && data.params && j.params && data.params.start === j.params.start && data.params.ziel === j.params.ziel);
    if (!gleicheStrecke) etappeOffen = new Set([1]);
    data = j; selection = {};
    setBahn(!!j.params.bahnhoefe_zeigen);
    const a = j.alternativen[0];
    const sek = ((performance.now() - t0) / 1000).toFixed(1);
    addMsg(`${diff.length && vorher ? "✓ Planung angepasst:" : "✓ Neue Planung:"}
      ${diff.length && vorher ? `<div class="diff">${diff.join("<br>")}</div>` : ` ${esc(j.params.start)} → ${esc(j.params.ziel)}, ${a.laenge_km} km in ${a.etappen.length} Etappe${a.etappen.length > 1 ? "n" : ""}.`}
      ${j.wetter_wahl ? (() => { const g = j.wetter_wahl.kandidaten.find(k => k.gewaehlt) || {}; return `<br>🌤️ ${g.bester ? "Bester Tag" : "Start"}: <b>${new Date(g.start).toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "numeric" })}</b>${g.trocken ? " – trocken" : ` – ${g.regen_mm} mm Regen`}${j.wetter_wahl.kriterium === "rueckenwind" && g.gegenwind_kmh != null
        ? (g.gegenwind_kmh <= -3 ? `, Rückenwind (≈ ${Math.round(-g.gegenwind_kmh)} km/h)` : g.gegenwind_kmh < 3 ? ", kaum Gegenwind" : `, leider ${Math.round(g.gegenwind_kmh)} km/h Gegenwind (bester Kompromiss mit Regen)`) : ""}`; })() : ""}
      ${(j.params.vorlieben || []).length ? `<br><span class="src">Berücksichtigt: ${j.params.vorlieben.map(v => esc(VORLIEBE_LABEL[v] || v)).join(", ")}</span>` : ""}
      ${(j.params.voreinst_genutzt || []).length ? `<br><span class="src">Aus deinen Voreinstellungen: ${j.params.voreinst_genutzt.map(k => esc(zeigeWert(k, j.params[k]))).join(", ")}</span>` : ""}
      ${(j.poi_auswahl || []).length ? `<br>${j.poi_auswahl.map(g => `${g.icon} ${esc(g.label)}`).join(", ")}: bitte in der Planung auswählen →` : ""}
      <div class="src">${sek} s${j.zeiten ? ` · Verstehen ${j.zeiten.llm ?? 0} s · Ortssuche ${j.zeiten.ortssuche ?? 0} s · Routing ${j.zeiten.routing ?? 0} s` : ""}</div>`);
    showAlt(0, gleicheStrecke);  // bei Änderungen an derselben Strecke Kartenausschnitt beibehalten
    $("planscroll").scrollTop = 0;
  } catch (e) {
    wait.remove(); addMsg("Backend nicht erreichbar: " + esc(e.message), "err");
  } finally { $("send").disabled = false; }
}

const POI_ICON = { fahrradladen: "🔧", verleih: "🚲", wegpunkt: "📍" };
const VORLIEBE_LABEL = { flach: "möglichst flach", ruhig: "wenig Verkehr", leise: "leise", wasser: "am Wasser",
  wald: "durch Wald & Grün", land: "Städte meiden", radrouten: "ausgeschilderte Radrouten", asphalt: "asphaltiert",
  kurz: "möglichst kurz", keine_treppen: "ohne Treppen (Anhänger)", keine_faehre: "ohne Fähre" };
const variantenName = (a, j) => a.titel || (a.ueber?.length === 1 ? a.ueber[0] : "Variante " + String.fromCharCode(65 + (typeof a.idx === "number" ? a.idx : j)));

function poiPopup(p, zusatz) {
  return `<b>${POI_ICON[p.kat] || "📍"} ${esc(p.name || "(ohne Namen)")}</b>${p.detail ? ` · ${esc(p.detail)}` : ""}<br>${esc(p.adresse || p.ort || "")}<br>${zusatz}
    ${p.web ? `<br><a target="_blank" href="${esc(p.web.startsWith("http") ? p.web : "https://" + p.web)}">Website</a>` : ""}
    <div class="src">Quelle: ${esc(p.quelle || "OpenStreetMap (ODbL)")}</div>`;
}

function viaWaehlen(kat, k) {
  const g = (data.poi_auswahl || []).find(x => x.kategorie === kat);
  const p = g && g.kandidaten[k];
  if (!p) return;
  const params = { ...data.params, nur_variante: aktuelleVariante(), via_pois: [...(data.params.via_pois || []), { kat, name: p.name, lon: p.lon, lat: p.lat, detail: p.detail, ort: p.ort, adresse: p.adresse, web: p.web, quelle: p.quelle }], bestaetigt: true };
  map.closePopup();
  send(`${g.icon} ${p.name} als Zwischenstopp`, params);
}

function chooseOption(k) {
  const o = pendingOptions[k];
  if (!o) return;
  pendingOptions = [];
  send(o.label, o.params);
}

// ---------- Hilfe „Was kann ich fragen?“ (eingeklappt im Begrüßungstext)
const HILFE = [
  ["Strecke & Tage", "Von Mainz nach Koblenz in 2 Tagen"],
  ["Radfernweg", "3 Tage auf dem Weserradweg ab Hann. Münden"],
  ["Rundtour", "60 km Rundtour ab Oldenburg"],
  ["Gutes Wetter", "In den nächsten 7 Tagen von Bremen nach Hamburg, wenn es trocken ist"],
  ["Rückenwind", "Von Bremen nach Oldenburg, an dem Tag mit Rückenwind"],
  ["Vorlieben", "Von Bonn nach Koblenz, möglichst flach, wenig Verkehr und am Wasser"],
  ["Familie & Anhänger", "Mit Kinderanhänger von Münster nach Telgte"],
  ["Rad & Untergrund", "Mit dem Rennrad von Hamburg nach Lübeck, nur Asphalt"],
  ["Übernachten", "2 Tage von Hann. Münden nach Höxter, mit Campingplatz"],
  ["Stopps", "Von Würzburg nach Bamberg mit Fahrradwerkstatt unterwegs"],
  ["Bahn als Notausstieg", "Von Erfurt nach Weimar, zeig mir die Bahnhöfe"],
  ["Danach ändern", "„lieber 3 Tage“, „über Rüdesheim“, „ohne Campingplatz“ – einfach weiterschreiben"],
];
function hilfeAufbauen() {
  const ul = $("hilfeListe"); if (!ul) return;
  ul.innerHTML = HILFE.map(([t, b], k) => `<li><b>${esc(t)}:</b> ${b.startsWith("„") ? esc(b)
    : `<a href="#" onclick="hilfeNehmen(${k});return false">„${esc(b)}“</a>`}</li>`).join("");
}
function hilfeNehmen(k) {
  const f = $("input"); f.value = HILFE[k][1]; f.focus();
  f.dispatchEvent(new Event("input"));
}
hilfeAufbauen();
