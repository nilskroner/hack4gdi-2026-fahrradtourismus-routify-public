// Routify – „Daten & Herkunft“: Planung als Linked Data (Routify-Ontologie, ausgerichtet an der GDI-DE-Radnetz-Ontologie)
// Holt Herkunft per SPARQL, bietet vordefinierte Fragen und Download als Turtle/JSON-LD.

let sparqlListe = null;

function ldAnfrage(extra = {}) {
  return { plan: data, variante: Math.max(0, data.alternativen.indexOf(current)), anfrage_text: lastText || null, ...extra };
}

function linkedDataKarte() {
  return `<details class="card" id="ldkarte" ontoggle="if (this.open) ldLaden()">
    <summary><b>Daten & Herkunft</b> <span class="src">Quellen und Lizenzen</span></summary>
    <div id="ldinhalt"><span class="src">Lädt beim Öffnen …</span></div>
  </details>`;
}

async function ldPost(pfad, body) {
  const r = await fetch(pfad, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok || j.fehler) throw new Error(j.fehler || "Server-Fehler");
  return j;
}

async function ldLaden() {
  const box = $("ldinhalt");
  if (!box || !data) return;
  try {
    if (!sparqlListe) sparqlListe = (await (await fetch("/api/sparql/abfragen")).json()).abfragen || [];
    const q = await ldPost("/api/sparql", ldAnfrage({ abfrage: "quellen" }));
    box.innerHTML = `
      <div class="src" style="margin-bottom:6px">Jede Angabe dieser Tour ist mit ihrer Quelle verknüpft, beschrieben nach dem
        <a href="/ontologie/routify.ttl" target="_blank">Radnetz-Datenmodell</a> der GDI-DE. Gemeinden sind über den amtlichen
        Gemeindeschlüssel mit Wikidata verbunden.</div>
      ${ldTabelle(q)}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">
        <select id="ldfrage" style="flex:1;min-width:160px">${sparqlListe.map(a => `<option value="${esc(a.id)}">${esc(a.titel)}</option>`).join("")}</select>
        <button class="btn" onclick="ldFragen()">Fragen</button>
      </div>
      <div id="ldergebnis"></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
        <button class="btn" onclick="ldDownload('turtle')">⬇ Daten exportieren (.ttl)</button>
        <button class="btn" onclick="ldDownload('jsonld')">⬇ Daten exportieren (.jsonld)</button>
      </div>`;
  } catch (e) { box.innerHTML = `<span class="empty">Daten & Herkunft nicht verfügbar: ${esc(e.message)}</span>`; }
}

// Spaltennamen der SPARQL-Variablen lesbar machen
const LD_KOPF = { tag: "Tag", datum: "Datum", km: "km", hm: "Hm", maxSteigung: "max. Steigung", radwegAnteil: "Radweg",
  datensatz: "Datensatz", titel: "Quelle", objekte: "Objekte", gemeinde: "Gemeinde", wikidata: "Wikidata",
  regionalschluessel: "Regionalschlüssel", name: "Name", unterkunft: "Unterkunft", ort: "Ort", bahnhof: "Bahnhof",
  abstandKm: "Abstand km", routenKm: "bei km", lizenz: "Lizenz", text: "Anfrage", parameter: "Parameter" };
const ldKopf = k => LD_KOPF[k] || k.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, c => c.toUpperCase());

function ldZelle(k, v) {
  if (v == null || v === "") return "";
  v = String(v);
  if (/^https?:\/\//.test(v)) {
    const q = v.match(/wikidata\.org\/entity\/(Q\d+)/);  // Wikidata-ID zeigen, sonst nur ein Link-Symbol
    return `<a href="${esc(v)}" target="_blank" title="${esc(v)}">${q ? q[1] + " ↗" : "↗"}</a>`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(v).toLocaleDateString("de-DE", { day: "numeric", month: "numeric" });
  if (/anteil/i.test(k) && !isNaN(v)) return Math.round(v * 100) + " %";
  if (/steigung/i.test(k) && !isNaN(v)) return String(v).replace(".", ",") + " %";
  if (!isNaN(v) && v.includes(".")) return String(Math.round(v * 10) / 10).replace(".", ",");
  return esc(v);
}

function ldTabelle(q) {
  if (!q.zeilen || !q.zeilen.length) return `<div class="src">Keine Treffer.</div>`;
  const zelle = (v, k) => ldZelle(k, v);
  // reine Verweis-Spalten (Datensatz-URI neben seinem Titel) ausblenden
  const spalten = q.kopf.map((k, i) => [k, i]).filter(([k]) => !(k === "datensatz" && q.kopf.includes("titel")));
  q = { ...q, kopf: spalten.map(([k]) => k), zeilen: q.zeilen.map(z => Array.isArray(z) ? spalten.map(([, i]) => z[i]) : z) };
  return `<div class="ldwrap"><table class="ldtab"><tr>${q.kopf.map(k => `<th>${esc(ldKopf(k))}</th>`).join("")}</tr>
    ${q.zeilen.slice(0, 40).map(z => `<tr>${q.kopf.map((k, i) => `<td>${zelle(Array.isArray(z) ? z[i] : z[k], k)}</td>`).join("")}</tr>`).join("")}</table></div>
    ${q.zeilen.length > 40 ? `<div class="src">… ${q.zeilen.length - 40} weitere</div>` : ""}`;
}

async function ldFragen() {
  const id = $("ldfrage").value, aus = $("ldergebnis");
  aus.innerHTML = `<span class="spinner"></span>`;
  try {
    const q = await ldPost("/api/sparql", ldAnfrage({ abfrage: id }));
    aus.innerHTML = `${ldTabelle(q)}<details style="margin-top:4px"><summary class="src">Technische Abfrage anzeigen</summary><pre class="ldsparql">${esc(q.sparql)}</pre></details>`;
  } catch (e) { aus.innerHTML = `<span class="empty">${esc(e.message)}</span>`; }
}

async function ldDownload(format) {
  try {
    const j = await ldPost("/api/rdf", ldAnfrage({ format }));
    const blob = new Blob([j.daten], { type: format === "turtle" ? "text/turtle" : "application/ld+json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `routify_${(data.params.start || "tour")}_${(data.params.ziel || "")}.${format === "turtle" ? "ttl" : "jsonld"}`.replace(/\s+/g, "_");
    a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { addMsg("Export fehlgeschlagen: " + esc(e.message), "err"); }
}

// ---------- Prüfung mit SHACL: Wünsche aus der Anfrage als Regeln gegen den RDF-Graphen der Tour
// Ergebnis je Variante (und Wegpunkt-Stand) zwischengespeichert, damit Umschalten nicht neu prüft.
const PRUEF_ICON = { ok: "✓", warnung: "!", verletzt: "✕" };

function pruefKarte() {
  return `<details class="card pruef" id="pruefung"><summary><span class="pruef-kopf"><span class="spinner"></span>Prüfe die Tour gegen deine Wünsche …</span></summary></details>`;
}

async function pruefungLaden() {
  const box = $("pruefung");
  if (!box || !data || !current) return;
  const variante = Math.max(0, data.alternativen.indexOf(current));
  const schluessel = variante + "|" + JSON.stringify(data.params.via_pois || []) + JSON.stringify(data.params.naechte || []);
  data._pruefung ||= {};
  let j = data._pruefung[schluessel];
  if (!j) {
    try { j = await ldPost("/api/pruefen", ldAnfrage({})); data._pruefung[schluessel] = j; }
    catch (e) { box.remove(); return; }  // Prüfung ist eine Zugabe – ohne sie bleibt die Planung vollständig
  }
  if ($("pruefung") !== box || data.alternativen.indexOf(current) !== variante) return;  // inzwischen neu gezeichnet
  const offen = j.regeln.filter(r => r.status !== "ok").length;
  const kopf = j.wuensche_gesamt
    ? `${j.wuensche_erfuellt === j.wuensche_gesamt ? "✓" : "!"} <b>${j.wuensche_erfuellt} von ${j.wuensche_gesamt} Wünschen erfüllt</b>`
    : `✓ <b>Tour geprüft</b>`;
  box.className = "card pruef " + (j.regeln.some(r => r.status === "verletzt") ? "rot" : offen ? "gelb" : "gruen");
  const zeile = (r) => `<li class="${r.status}"><span class="pi">${PRUEF_ICON[r.status]}</span><span>${esc(r.regel)}
      ${r.details.length ? `<small>${r.details.map(esc).join(" · ")}</small>` : ""}</span></li>`;
  const wunsch = j.regeln.filter(r => r.art === "wunsch"), standard = j.regeln.filter(r => r.art === "standard");
  box.innerHTML = `<summary><span class="pruef-kopf">${kopf}</span>
      <span class="src">Grundregeln ${j.standard_erfuellt}/${j.standard_gesamt}</span></summary>
    ${wunsch.length ? `<div class="pruef-titel">Deine Wünsche</div><ul class="pruefliste">${wunsch.map(zeile).join("")}</ul>` : ""}
    <div class="pruef-titel">Grundregeln</div><ul class="pruefliste">${standard.map(zeile).join("")}</ul>
    <div class="src" style="margin-top:8px">Deine Wünsche werden zu Regeln und automatisch gegen die fertige Tour geprüft.</div>
    <details style="margin-top:4px"><summary class="src">Regeln im Detail (technisch)</summary><pre class="ldsparql">${esc(j.shacl)}</pre></details>`;
}
