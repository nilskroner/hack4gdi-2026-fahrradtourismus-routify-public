// Routify – Wegpunkte bearbeiten, Übernachtungen, Wetter-Tag, Etappen ein-/ausklappen
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// ---------- Wegpunkte bearbeiten (Reihenfolge, entfernen, Übernachtungen)
const WP_FELDER = ["kat", "name", "lon", "lat", "detail", "ort", "adresse", "telefon", "web", "quelle", "typ", "art", "typen"];
const nurFelder = (o) => Object.fromEntries(WP_FELDER.filter(k => o[k] !== undefined).map(k => [k, o[k]]));

function wpListe() {
  return (current && current.wegpunkte) || (data && data.wegpunkte) || [];
}

function wpParams(liste, extra = {}) {
  // Liste der Zwischenpunkte in gewünschter Reihenfolge -> Parameter fürs Backend
  return { ...data.params, nur_variante: aktuelleVariante(), ...extra, bestaetigt: true,
    wegpunkte: liste.map(w => ({ typ: w.typ, name: w.name })),
    zwischenziele: liste.filter(w => w.typ === "ort").map(w => w.name),
    via_pois: liste.filter(w => w.typ === "poi").map(nurFelder),
    uebernachtungen: liste.filter(w => w.typ === "nacht").map(nurFelder) };
}

function wpVerschieben(k, d) {
  const l = [...wpListe()];
  [l[k], l[k + d]] = [l[k + d], l[k]];
  send(`↕ ${l[k + d].name} ${d < 0 ? "nach vorn" : "nach hinten"} verschoben`, wpParams(l));
}

function wpEntfernen(k) {
  const w = wpListe()[k];
  const l = wpListe().filter((_, i) => i !== k);
  // entfernter Wunsch-Stopp: Kategorie nicht erneut vorschlagen
  const extra = w.typ === "poi" ? { poi_wuensche: (data.params.poi_wuensche || []).filter(x => x.kategorie !== w.kat) } : {};
  send(`✕ ${w.name} entfernt`, wpParams(l, extra));
}

function wpHinzu() {
  const name = $("wpNeu").value.trim();
  if (!name) return;
  send(`＋ Zwischenziel ${name}`, wpParams([...wpListe(), { typ: "ort", name }]));
}

function wpTauschen() {
  const l = [...wpListe()].reverse();
  send(`⇅ Start und Ziel getauscht`, wpParams(l, { start: data.params.ziel, ziel: data.params.start, nur_variante: null }));
}

function uebernachten(nr, k) {
  const s = current.etappen.find(x => x.nr === nr);
  const u = s.unterkuenfte[k];
  // bisherige Übernachtung derselben Nacht (falls vorhanden) ersetzen
  const l = wpListe().filter(w => !(w.typ === "nacht" && s.uebernachtung && w.name === s.uebernachtung.name));
  l.push({ ...nurFelder(u), art: u.art || u.typ, typ: "nacht" });  // typ = Rolle als Wegpunkt, art = Unterkunftsart (camp_site …)
  map.closePopup();
  send(`🛏️ Tag ${nr}: Übernachtung in ${u.name || "Unterkunft"}`, wpParams(l));
}

function nachtEntfernen(name) {
  const l = wpListe().filter(w => !(w.typ === "nacht" && w.name === name));
  send(`🛏️ Übernachtung ${name} entfernt`, wpParams(l));
}

function aktuelleVariante() {
  // Index der Variante im Backend (A=0, B=1, C=2); bleibt über Änderungen hinweg gleich
  return current && typeof current.idx === "number" ? current.idx : null;
}

function alleVarianten() {
  send("Alle Varianten wieder anzeigen", { ...data.params, nur_variante: null, bestaetigt: true });
}

function wetterTag(tag) {
  send(`🌤️ Start am ${new Date(tag).toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "numeric" })}`,
       { ...data.params, nur_variante: aktuelleVariante(), wetter_tag: tag, bestaetigt: true });
}

// Etappen ein-/ausklappen (eintägige Touren und neue Planungen: erste Etappe offen)
let etappeOffen = new Set([1]);
function etappeUmschalten(nr) {
  etappeOffen.has(nr) ? etappeOffen.delete(nr) : etappeOffen.add(nr);
  renderSidebar(data.alternativen.indexOf(current));
}
function alleEtappen(auf) {
  etappeOffen = auf ? new Set(current.etappen.map(s => s.nr)) : new Set();
  renderSidebar(data.alternativen.indexOf(current));
}
