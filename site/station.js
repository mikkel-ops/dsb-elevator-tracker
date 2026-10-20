import { api, duration, el, evidenceLinks, fmtDate, fmtDateTime, showError } from "./common.js";

const slug = new URLSearchParams(location.search).get("s") ?? "";
const tbody = document.getElementById("incidents");

try {
  const { station, incidents } = await api(`/api/stations/${encodeURIComponent(slug)}`);
  document.title = `${station} – Hvor længe har elevatoren været ude af drift?`;
  document.getElementById("title").textContent = station;
  const open = incidents.filter((i) => !i.end).length;
  document.getElementById("summary").textContent =
    `${incidents.length} registrerede hændelser, heraf ${open} ude af drift lige nu.`;

  const now = Date.now();
  tbody.replaceChildren(...incidents.map((i) => {
    const days = ((i.end ? Date.parse(i.end) : now) - Date.parse(i.start)) / 864e5;
    const docs = el("td", {});
    evidenceLinks(i.start, "Start").then((n) => docs.append(n));
    if (i.end) evidenceLinks(i.end, "Slut").then((n) => docs.append(el("div", {}, n)));
    return el("tr", {},
      el("td", {}, i.location || "Elevator", el("div", { class: "type" }, i.label)),
      el("td", {},
        `${i.start_is_lower_bound ? "før " : ""}${fmtDateTime(i.start)} – `,
        i.end ? fmtDateTime(i.end) : el("strong", {}, "stadig ude af drift"),
        i.end_is_precise ? null : el("div", { class: "type" }, "sluttidspunkt upræcist (hul i indsamlingen)")),
      el("td", { class: "num" }, duration(days, i.start_is_lower_bound)),
      el("td", {},
        i.expected_history.length ? i.expected_history.map(fmtDate).join(" → ") : i.status_text),
      docs);
  }));
} catch (err) {
  showError(tbody, err);
}
