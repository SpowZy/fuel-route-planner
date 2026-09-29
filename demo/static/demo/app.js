"use strict";

const PRESETS = [
  { label: "Chicago to Nashville", note: "Under one tank: no stop needed", start: "Chicago, IL", finish: "Nashville, TN" },
  { label: "New York to Los Angeles", note: "Coast to coast", start: "New York, NY", finish: "Los Angeles, CA" },
  { label: "Houston to Denver", note: "Where the price trade-off shows", start: "Houston, TX", finish: "Denver, CO" },
];
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
const RASTER_FALLBACK = {
  version: 8,
  sources: { osm: { type: "raster", tileSize: 256, attribution: "© OpenStreetMap contributors",
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"] } },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const $ = (selector) => document.querySelector(selector);
const money = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const priceColor = (price, lo, hi) => {
  const t = hi > lo ? (price - lo) / (hi - lo) : 0;
  return `hsl(${Math.round(140 - 140 * t)} 78% 56%)`;
};

let map, data, replayFrame, truck;

function initMap() {
  map = new maplibregl.Map({ container: "map", style: STYLE_URL, center: [-96, 38.5], zoom: 3.4, attributionControl: true });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  let fellBack = false;
  map.on("error", (event) => {
    if (!fellBack && event.error && /style|tiles\.openfreemap/i.test(String(event.error.message || event.error))) {
      fellBack = true;
      map.setStyle(RASTER_FALLBACK);
    }
  });
}

function drawRoute(payload) {
  const lines = payload.map.geojson.features.filter((f) => f.properties.kind === "route");
  const apply = () => {
    for (const id of ["route-casing", "route"]) if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource("route")) map.removeSource("route");
    map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: lines } });
    map.addLayer({ id: "route-casing", type: "line", source: "route", paint: { "line-color": "#fff", "line-width": 8, "line-opacity": 0.9 }, layout: { "line-cap": "round", "line-join": "round" } });
    map.addLayer({ id: "route", type: "line", source: "route", paint: { "line-color": "#2f7bff", "line-width": 4.5 }, layout: { "line-cap": "round", "line-join": "round" } });
    const coords = payload.route.geometry.coordinates;
    const bounds = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]));
    map.fitBounds(bounds, { padding: { top: 60, bottom: 90, left: 60, right: 60 }, duration: 900 });
  };
  if (map.isStyleLoaded()) apply(); else map.once("idle", apply);
}

let markers = [];
function drawPins(payload) {
  markers.forEach((m) => m.remove());
  markers = [];
  const prices = payload.fuel_stops.map((s) => s.price_per_gallon);
  const [lo, hi] = [Math.min(...prices), Math.max(...prices)];
  const add = (lngLat, text, color, popup) => {
    const el = document.createElement("div");
    el.className = "pin";
    el.style.background = color;
    el.textContent = text;
    const marker = new maplibregl.Marker({ element: el }).setLngLat(lngLat);
    if (popup) marker.setPopup(new maplibregl.Popup({ offset: 16 }).setHTML(popup));
    marker.addTo(map);
    markers.push(marker);
  };
  const [first, ...rest] = payload.route.geometry.coordinates;
  add(first, "A", "#fff");
  add(rest[rest.length - 1], "B", "#fff");
  for (const s of payload.fuel_stops) {
    const st = s.station;
    add([st.longitude, st.latitude], s.order, priceColor(s.price_per_gallon, lo, hi),
      `<b>${st.name}</b><br>${st.city}, ${st.state}<br>${st.address}<br>` +
      `mile ${s.mile_marker} | $${s.price_per_gallon.toFixed(3)}/gal<br>` +
      `${s.gallons_purchased.toFixed(1)} gal = ${money(s.cost_usd)}<br><i>${s.decision}</i>`);
  }
}

function tankSeries(payload) {
  const v = payload.vehicle, total = payload.route.distance_miles, mpg = v.mpg;
  const points = [[0, v.start_fuel_gallons]];
  for (const s of payload.fuel_stops) {
    points.push([s.mile_marker, s.tank_gallons_before], [s.mile_marker, s.tank_gallons_after]);
  }
  const [lastMile, lastTank] = points[points.length - 1];
  points.push([total, Math.max(0, lastTank - (total - lastMile) / mpg)]);
  return points;
}

function drawChart(payload) {
  const W = 900, H = 200, pad = { l: 34, r: 10, t: 14, b: 22 };
  const total = payload.route.distance_miles, cap = payload.vehicle.tank_gallons;
  const x = (mile) => pad.l + (mile / total) * (W - pad.l - pad.r);
  const y = (gal) => H - pad.b - (gal / cap) * (H - pad.t - pad.b);
  const series = tankSeries(payload);
  const line = series.map(([m, g]) => `${x(m).toFixed(1)},${y(g).toFixed(1)}`).join(" ");
  const area = `${x(0)},${y(0)} ${line} ${x(total)},${y(0)}`;
  const prices = payload.fuel_stops.map((s) => s.price_per_gallon);
  const [lo, hi] = [Math.min(...prices), Math.max(...prices)];
  let svg = `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(cap)}" y2="${y(cap)}" stroke="#2a3644" stroke-dasharray="4 4"/>` +
    `<text x="4" y="${y(cap) + 4}" fill="#8a99ab" font-size="11">${cap.toFixed(0)}</text>` +
    `<text x="4" y="${y(0) + 4}" fill="#8a99ab" font-size="11">0</text>` +
    `<text x="${pad.l}" y="${H - 4}" fill="#8a99ab" font-size="11">0 mi</text>` +
    `<text x="${W - pad.r}" y="${H - 4}" fill="#8a99ab" font-size="11" text-anchor="end">${total.toFixed(0)} mi</text>` +
    `<polygon points="${area}" fill="rgba(61,220,151,.14)"/>` +
    `<polyline points="${line}" fill="none" stroke="#3ddc97" stroke-width="2.2" stroke-linejoin="round"/>`;
  for (const s of payload.fuel_stops) {
    const color = priceColor(s.price_per_gallon, lo, hi);
    svg += `<circle cx="${x(s.mile_marker)}" cy="${y(s.tank_gallons_after)}" r="5" fill="${color}" stroke="#0b0f14" stroke-width="1.5"/>` +
      `<text x="${x(s.mile_marker)}" y="${y(s.tank_gallons_after) - 9}" fill="#e8edf3" font-size="11" text-anchor="middle">$${s.price_per_gallon.toFixed(2)}</text>`;
  }
  svg += `<line id="cursor" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" stroke="#f5a524" stroke-width="1.5" visibility="hidden"/>`;
  $("#chart").innerHTML = svg;
  return { x, series };
}

function drawTable(payload) {
  $("#stops tbody").innerHTML = payload.fuel_stops.length
    ? payload.fuel_stops.map((s) => `<tr><td>${s.order}</td><td>${s.station.name}, ${s.station.city} ${s.station.state}</td>` +
        `<td>${s.mile_marker}</td><td>$${s.price_per_gallon.toFixed(3)}</td><td>${s.gallons_purchased.toFixed(1)}</td>` +
        `<td>${money(s.cost_usd)}</td><td class="decision">${s.decision}</td></tr>`).join("")
    : `<tr><td colspan="7" class="decision">${payload.summary}.</td></tr>`;
}

function render(payload, clientMs) {
  data = payload;
  const totals = payload.totals;
  $("#kpis").hidden = false;
  $("#details").hidden = false;
  $("#hud").hidden = false;
  $("#replay").hidden = false;
  $("#k-cost").textContent = money(totals.fuel_cost_usd);
  $("#k-stops").textContent = totals.stops;
  $("#k-saved").textContent = totals.savings_vs_baseline_usd == null ? "n/a" : money(totals.savings_vs_baseline_usd);
  $("#k-ms").textContent = `${Math.round(clientMs)} ms`;
  const calls = payload.meta.external_calls;
  $("#k-calls").textContent = `${calls} (${payload.meta.routing.source})`;
  $("#status").className = "";
  $("#status").textContent = `${payload.summary}. ${payload.route.distance_miles.toFixed(0)} mi, ${payload.route.duration_hours.toFixed(1)} h of driving.`;
  $("#raw").textContent = JSON.stringify({ ...payload, map: { url: payload.map.url, geojson: "(FeatureCollection, omitted here)" }, route: { ...payload.route, geometry: "(LineString, omitted here)" } }, null, 2);
  drawRoute(payload);
  drawPins(payload);
  drawTable(payload);
  chart = drawChart(payload);
  stopReplay();
}
let chart;

async function plan(start, finish) {
  stopReplay();
  $("#status").className = "";
  $("#status").textContent = "Planning...";
  const params = new URLSearchParams({ start, finish });
  if ($("#nocache").checked) params.set("nocache", "1");
  history.replaceState(null, "", `?${new URLSearchParams({ start, finish })}`);
  const began = performance.now();
  try {
    const response = await fetch(`/api/v1/route/?${params}`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.error ? body.error.message : "Request failed");
    render(body, performance.now() - began);
  } catch (error) {
    $("#status").className = "error";
    $("#status").textContent = error.message;
  }
}

function cumulative(coords, total) {
  const out = [0];
  for (let i = 1; i < coords.length; i++) {
    const [lo1, la1] = coords[i - 1], [lo2, la2] = coords[i];
    const dx = (lo2 - lo1) * Math.cos(((la1 + la2) / 2) * Math.PI / 180), dy = la2 - la1;
    out.push(out[i - 1] + Math.hypot(dx, dy));
  }
  const scale = total / out[out.length - 1];
  return out.map((d) => d * scale);
}

function stopReplay() {
  cancelAnimationFrame(replayFrame);
  if (truck) { truck.remove(); truck = null; }
  const cursor = $("#cursor");
  if (cursor) cursor.setAttribute("visibility", "hidden");
}

function replay() {
  if (!data) return;
  stopReplay();
  const coords = data.route.geometry.coordinates, total = data.route.distance_miles;
  const cum = cumulative(coords, total), series = tankSeries(data);
  const el = document.createElement("div");
  el.className = "truck";
  el.textContent = "\u{1F69B}";
  truck = new maplibregl.Marker({ element: el }).setLngLat(coords[0]).addTo(map);
  const cursor = $("#cursor"), duration = 14000, began = performance.now();
  const tankAt = (mile) => {
    for (let i = 1; i < series.length; i++) {
      if (mile <= series[i][0] && series[i][0] > series[i - 1][0]) {
        const [m0, g0] = series[i - 1], [m1, g1] = series[i];
        return g0 + ((mile - m0) / (m1 - m0)) * (g1 - g0);
      }
      if (mile === series[i][0] && series[i][0] === series[i - 1][0]) return series[i][1];
    }
    return series[series.length - 1][1];
  };
  const frame = (now) => {
    const t = Math.min(1, (now - began) / duration), mile = t * total;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (cum[mid] <= mile) lo = mid; else hi = mid; }
    const f = cum[hi] > cum[lo] ? (mile - cum[lo]) / (cum[hi] - cum[lo]) : 0;
    truck.setLngLat([coords[lo][0] + f * (coords[hi][0] - coords[lo][0]), coords[lo][1] + f * (coords[hi][1] - coords[lo][1])]);
    const px = chart.x(mile);
    cursor.setAttribute("x1", px); cursor.setAttribute("x2", px); cursor.setAttribute("visibility", "visible");
    const spent = data.fuel_stops.filter((s) => s.mile_marker <= mile).reduce((sum, s) => sum + s.cost_usd, 0);
    $("#hud-tank").textContent = `${tankAt(mile).toFixed(1)} gal`;
    $("#hud-mile").textContent = Math.round(mile).toLocaleString("en-US");
    $("#hud-spent").textContent = money(spent);
    if (t < 1) replayFrame = requestAnimationFrame(frame);
  };
  replayFrame = requestAnimationFrame(frame);
}

function init() {
  $("#presets").innerHTML = PRESETS.map((p, i) => `<button class="preset" data-i="${i}"><b>${p.label}</b><small>${p.note}</small></button>`).join("");
  $("#presets").addEventListener("click", (event) => {
    const button = event.target.closest(".preset");
    if (!button) return;
    const preset = PRESETS[Number(button.dataset.i)];
    $("#start").value = preset.start;
    $("#finish").value = preset.finish;
    plan(preset.start, preset.finish);
  });
  $("#form").addEventListener("submit", (event) => {
    event.preventDefault();
    plan($("#start").value.trim(), $("#finish").value.trim());
  });
  $("#replay").addEventListener("click", replay);
  initMap();
  const query = new URLSearchParams(location.search);
  if (query.get("start") && query.get("finish")) {
    $("#start").value = query.get("start");
    $("#finish").value = query.get("finish");
    map.once("load", () => plan(query.get("start"), query.get("finish")));
  }
}

init();
