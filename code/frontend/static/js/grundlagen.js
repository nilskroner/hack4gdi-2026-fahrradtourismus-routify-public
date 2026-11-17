// Routify – Grundlagen: Konstanten, Zustand, Hilfsfunktionen
// (klassisches Skript; gemeinsame Namen liegen global, Reihenfolge siehe index.html)

// Routenfarben bewusst „kartenfremd“: kein Grün (Wald), Blau (Wasser), Lila (Radrouten in CyclOSM), Gelb (Straßen)
const COLORS = ["#e6007e", "#ff6d00", "#ffd600", "#00b3c7"];
// Rand je Variante: Gelb braucht einen dunklen Rand, sonst verschwindet es auf hellen Karten
const CASING = ["#ffffff", "#ffffff", "#4a3f00", "#ffffff"];
// Etwas dunklere Töne für das Höhenprofil (heller Hintergrund)
const CHART_COLORS = ["#e6007e", "#ff6d00", "#d4a800", "#0098aa"];
// Farbe/Buchstabe hängen an der Variante (Backend-Index), nicht an der Position – bleibt bei ausgeblendeten Varianten gleich
const vIdx = (j) => (data && data.alternativen[j] && typeof data.alternativen[j].idx === "number") ? data.alternativen[j].idx : j;
const pinText = (c) => (c === COLORS[2] ? "#222" : "#fff");

// Wegtypen und Untergründe – Reihenfolge = Reihenfolge in den Balken (gut → kritisch)
const WEGTYP = {
  radweg:         { l: "Radweg",                  ic: "🚲", c: "#2a9d5c" },
  radstreifen:    { l: "Straße mit Radstreifen",  ic: "🛣️", c: "#8cc084" },
  ruhig:          { l: "Ruhige Straße",           ic: "🏘️", c: "#9aa5b1" },
  wirtschaftsweg: { l: "Wirtschafts-/Feldweg",    ic: "🌾", c: "#c9a66b" },
  pfad:           { l: "Pfad / Fußweg",           ic: "🥾", c: "#a07cc5" },
  faehre:         { l: "Fähre",                   ic: "⛴️", c: "#3a86ff" },
  hauptstrasse:   { l: "Hauptstraße mit Verkehr", ic: "⚠️", c: "#d1495b" },
};
const UNTERGRUND = {
  asphalt:     { l: "Asphalt / glatt",  ic: "⬛", c: "#4f5b66" },
  pflaster:    { l: "Pflaster",         ic: "🧱", c: "#b5651d" },
  schotter:    { l: "Fester Schotter",  ic: "🪨", c: "#e0b84f" },
  unbefestigt: { l: "Unbefestigt",      ic: "🌱", c: "#7a8f3c" },
  unbekannt:   { l: "Unbekannt",        ic: "❔", c: "#d5d5d5" },
};
let colorMode = "variante";  // Routen auf der Karte einfärben nach: variante | wegtyp | untergrund

function bar(dist, cats, cls = "") {
  const total = Object.values(dist || {}).reduce((a, b) => a + b, 0) || 1;
  return `<div class="bar ${cls}">${Object.entries(cats).filter(([k]) => dist?.[k]).map(([k, c]) => {
    const pct = dist[k] / total * 100;
    return `<span style="width:${pct}%;background:${c.c}" title="${c.l}: ${(dist[k] / 1000).toFixed(1)} km (${Math.round(pct)} %)"></span>`;
  }).join("")}</div>`;
}

function barLegend(dist, cats) {
  const total = Object.values(dist || {}).reduce((a, b) => a + b, 0) || 1;
  return Object.entries(cats).filter(([k]) => dist?.[k] >= 50).map(([k, c]) =>
    `<div title="${(dist[k] / 1000).toFixed(1)} km"><span class="sw" style="background:${c.c}"></span><span style="flex:1">${c.l}</span><b class="pc">${Math.round(dist[k] / total * 100)} %</b></div>`).join("");
}

let bahnZeigen = false;  // Notausstiege sichtbar? (berechnet werden sie immer)

function setBahn(an) {
  if (bahnZeigen === an && map.hasLayer(layers.bahnhof) === an) return;
  bahnZeigen = an;
  if (an && !map.hasLayer(layers.bahnhof)) layers.bahnhof.addTo(map);
  if (!an && map.hasLayer(layers.bahnhof)) map.removeLayer(layers.bahnhof);
  if (data && current) renderSidebar(data.alternativen.indexOf(current));
}

function setColorMode(m) {
  colorMode = m;
  if (data && current) showAlt(data.alternativen.indexOf(current), true);
}
const KAT = {
  unterkunft:   { ic: "🛏️", label: "Unterkunft", color: "#c0392b" },
  fahrradladen: { ic: "🔧", label: "Fahrradladen", color: "#d35400" },
  reparatur:    { ic: "🛠️", label: "Reparaturstation", color: "#7f8c8d" },
  verleih:      { ic: "🚲", label: "Fahrradverleih", color: "#2980b9" },
  bahnhof:      { ic: "🚉", label: "Bahnhof", color: "#34495e" },
};
const TYP = { hotel: "Hotel", guest_house: "Pension", hostel: "Hostel", camp_site: "Campingplatz",
              motel: "Motel", apartment: "Ferienwohnung", chalet: "Ferienhaus" };
const WETTER = { dry: "☀️ trocken", rain: "🌧️ Regen", snow: "🌨️ Schnee", fog: "🌫️ Nebel",
                 thunderstorm: "⛈️ Gewitter", sleet: "🌨️ Schneeregen", hail: "🌨️ Hagel" };

// Zustand (muss vor Chart/Karte stehen, weil das Diagramm beim Anlegen schon zeichnet)
let data = null, current = null, selection = {};

const $ = (id) => document.getElementById(id);
const ICON_NUTZER = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>';
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Fahrzeit in Worten: 2.4 -> "≈ 2 h 25 min"
function fahrzeitText(h) {
  if (h == null || isNaN(h)) return "–";
  const ges = Math.round(h * 60 / 5) * 5;
  const std = Math.floor(ges / 60), min = ges % 60;
  return ges ? `≈ ${std ? std + " h" : ""}${std && min ? " " : ""}${min ? min + " min" : ""}` : "–";
}
// Kurzform für Kennzahlen: 3.08 -> "3:05 h"
const fahrzeitKurz = h => h == null || isNaN(h) ? "–" : (m => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")} h`)(Math.round(h * 60 / 5) * 5);
