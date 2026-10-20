import { api, duration, el, fmtDate, fmtDateTime, num, showError, statusCell } from "./common.js";

const [stats, current, stations] = await Promise.all([
  api("/api/stats"),
  api("/api/current"),
  fetch("data/stations.json").then((r) => r.json()),
]).catch((err) => {
  showError(document.getElementById("kpis"), err);
  throw err;
});

renderKpis(stats);
renderCurrent(current);
renderMap(current, stations);
renderStationChart(stats.stations.filter((s) => s.days_down_12m > 0).slice(0, 15));
renderPromises(stats.promises);
document.getElementById("footer").textContent =
  `Senest opdateret ${fmtDateTime(stats.generated_at)}. ${stats.incident_count} hændelser registreret i alt.`;

function kpi(label, value, note) {
  return el("div", { class: "card kpi" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, value),
    note && el("div", { class: "note" }, note));
}

function renderKpis(s) {
  const r = s.repair_days;
  const pending = "kræver elevatorer, vi har set gå i stykker og blive repareret";
  document.getElementById("kpis").replaceChildren(
    kpi("Elevatorer ude af drift nu", s.open_now.total),
    kpi("Har overskredet DSB's forventede dato", s.open_now.overdue, "DSB's seneste dato, blandt dem der er ude af drift nu"),
    kpi("Median reparationstid", r.n ? duration(r.median) : "–", r.n ? `${r.n} afsluttede hændelser` : pending),
    kpi("Gennemsnitlig reparationstid", r.n ? duration(r.mean) : "–", r.n ? `længste ${duration(r.max)}` : pending),
  );
}

function renderCurrent(items) {
  document.getElementById("current-sub").textContent =
    `${items.length} elevatorer står på DSB's liste. Sorteret efter, hvor længe de har været ude af drift.`;
  const rows = items.map((i) =>
    el("tr", {},
      el("td", {},
        el("a", { href: `station.html?s=${encodeURIComponent(i.station_slug)}` }, i.station),
        el("div", { class: "type" }, i.location)),
      el("td", { class: "num" }, duration(i.days_down, i.start_is_lower_bound)),
      el("td", {}, i.latest_expected ? fmtDate(i.latest_expected) : "–",
        i.expected_changes ? el("div", { class: "type" }, `rykket ${i.expected_changes}×`) : null),
      el("td", {}, statusCell(i))));
  document.getElementById("current").replaceChildren(
    ...(rows.length ? rows : [el("tr", {}, el("td", { colspan: 4, class: "empty" }, "Intet ude af drift lige nu."))]));
}

function renderMap(items, stations) {
  const map = L.map("map", { scrollWheelZoom: false }).setView([56.0, 11.0], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const byStation = Map.groupBy(items, (i) => i.station_slug);
  const css = getComputedStyle(document.documentElement);
  const bounds = [];
  for (const [slug, incs] of byStation) {
    const st = stations[slug];
    if (!st) continue;
    const overdue = incs.some((i) => i.overdue);
    const marker = L.circleMarker([st.lat, st.lon], {
      radius: 7,
      weight: 2,
      color: css.getPropertyValue("--surface-1").trim(),
      fillColor: css.getPropertyValue(overdue ? "--critical" : "--series-1").trim(),
      fillOpacity: 1,
    }).addTo(map);
    const popup = el("div", {},
      el("strong", {}, incs[0].station),
      el("ul", { style: "padding-left: 16px; margin: 4px 0" },
        incs.map((i) => el("li", {},
          `${i.location || "Elevator"}: ${duration(i.days_down, i.start_is_lower_bound)}`,
          i.overdue ? " (lovet dato overskredet)" : ""))),
      el("a", { href: `station.html?s=${encodeURIComponent(slug)}` }, "Se historik"));
    marker.bindPopup(popup);
    bounds.push([st.lat, st.lon]);
  }
  if (bounds.length) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 11 });
}

function renderStationChart(rows) {
  const box = document.getElementById("stations-chart");
  if (!rows.length) {
    box.replaceChildren(el("p", { class: "empty" }, "Ingen data endnu."));
    return;
  }
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const W = 720, labelW = 150, valueW = 64, rowH = 28, barH = 16, top = 8, axisH = 24;
  const plotW = W - labelW - valueW;
  const max = Math.max(...rows.map((r) => r.days_down_12m));
  const step = niceStep(max);
  const xMax = Math.ceil(max / step) * step;
  const x = (v) => labelW + (v / xMax) * plotW;
  const H = top + rows.length * rowH + axisH;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Dage ude af drift pr. station, seneste 12 måneder" });

  for (let v = 0; v <= xMax; v += step) {
    root.append(svg("line", { x1: x(v), x2: x(v), y1: top, y2: H - axisH, stroke: "var(--grid)", "stroke-width": 1 }));
    root.append(svg("text", { x: x(v), y: H - 6, "text-anchor": "middle", class: "tick" }, num(v)));
  }
  const tip = el("div", { class: "tooltip", hidden: true });
  document.body.append(tip);

  rows.forEach((r, i) => {
    const y = top + i * rowH + (rowH - barH) / 2;
    const w = Math.max(x(r.days_down_12m) - labelW, 2);
    const rad = Math.min(4, w);
    root.append(svg("text", { x: labelW - 8, y: y + barH / 2 + 4, "text-anchor": "end" }, r.station));
    const hit = svg("rect", { x: 0, y: top + i * rowH, width: W, height: rowH, class: "hit", tabindex: 0 });
    const show = (ev) => {
      tip.replaceChildren(
        el("strong", {}, `${num(r.days_down_12m)} dage`),
        el("span", {}, `${r.station} · ${r.incidents} hændelser · længste ${duration(r.longest_days)}`));
      tip.hidden = false;
      const rect = ev.clientX ? { x: ev.clientX, y: ev.clientY } : hit.getBoundingClientRect();
      tip.style.left = `${Math.min(rect.x + 12, innerWidth - 260)}px`;
      tip.style.top = `${rect.y + 12}px`;
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", () => (tip.hidden = true));
    hit.addEventListener("blur", () => (tip.hidden = true));
    hit.addEventListener("click", () => (location.href = `station.html?s=${encodeURIComponent(r.station_slug)}`));
    root.append(hit);
    // Square at the baseline, 4px rounded data-end.
    root.append(svg("path", {
      class: "bar",
      d: `M${labelW},${y}h${w - rad}a${rad},${rad} 0 0 1 ${rad},${rad}v${barH - 2 * rad}a${rad},${rad} 0 0 1 -${rad},${rad}h-${w - rad}z`,
    }));
    root.append(svg("text", { x: labelW + w + 6, y: y + barH / 2 + 4, class: "value" }, num(r.days_down_12m)));
  });

  const table = el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Station"), el("th", { class: "num" }, "Dage ude af drift"),
      el("th", { class: "num" }, "Hændelser"), el("th", { class: "num" }, "Længste"))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", {}, el("a", { href: `station.html?s=${encodeURIComponent(r.station_slug)}` }, r.station)),
      el("td", { class: "num" }, num(r.days_down_12m)),
      el("td", { class: "num" }, r.incidents),
      el("td", { class: "num" }, duration(r.longest_days))))));
  box.replaceChildren(root, el("details", { class: "table-view" }, el("summary", {}, "Vis som tabel"), table));
}

function niceStep(max) {
  const raw = max / 5;
  const pow = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? pow * 10;
}

function renderPromises(p) {
  const box = document.getElementById("promises");
  const parts = [];
  if (p.closed_with_promise) {
    parts.push(el("p", {},
      `Af ${p.closed_with_promise} afsluttede hændelser med en forventet dato blev `,
      el("strong", {}, `${p.closed_late} (${num(p.closed_late_share * 100)} %)`),
      ` først løst efter datoen.`,
      p.overrun_days.n ? ` Når datoen blev overskredet, var det med ${duration(p.overrun_days.median)} i median.` : ""));
    if (p.date_moved) parts.push(el("p", {}, `DSB rykkede den forventede dato mindst én gang i ${p.date_moved} af hændelserne.`));
  } else {
    parts.push(el("p", { class: "muted" }, "Der er endnu ingen afsluttede hændelser at sammenligne med. Indsamlingen startede 20. oktober 2026, og tallene kommer, efterhånden som vi ser elevatorer blive repareret."));
  }
  parts.push(el("p", {}, `Lige nu er `, el("strong", {}, String(p.open_past_promise)),
    ` elevatorer stadig ude af drift, selvom datoen, DSB først oplyste, er passeret.`));
  box.replaceChildren(...parts);
}
