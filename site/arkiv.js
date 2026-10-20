import { API, api, el, fmtDateTime, showError } from "./common.js";

const input = document.getElementById("day");
const tbody = document.getElementById("snapshots");
const preview = document.getElementById("preview");
const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Copenhagen" }).format(new Date());
input.value = new URLSearchParams(location.search).get("day") ?? today;
input.max = today;
input.addEventListener("change", () => {
  history.replaceState(null, "", `?day=${input.value}`);
  load();
});
load();

async function load() {
  preview.replaceChildren();
  try {
    // SCRAPE keys are UTC; a Danish day spans two UTC dates, so fetch both.
    const d = new Date(`${input.value}T00:00:00`);
    const prev = new Date(d.getTime() - 864e5).toISOString().slice(0, 10);
    const lists = await Promise.all([api(`/api/snapshots?day=${prev}`), api(`/api/snapshots?day=${input.value}`)]);
    const local = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Copenhagen" });
    const items = lists.flat().filter((s) => local.format(new Date(s.at)) === input.value).reverse();
    tbody.replaceChildren(...(items.length ? items.map(row) : [el("tr", {}, el("td", { colspan: 5, class: "empty" }, "Ingen hentninger denne dag."))]));
  } catch (err) {
    showError(tbody, err);
  }
}

function row(s) {
  const shot = s.screenshot
    ? el("a", { href: API + s.screenshot.url, target: "_blank", rel: "noopener" }, "Åbn")
    : el("span", { class: "muted" }, "–");
  if (s.screenshot) {
    const btn = el("button", { type: "button" }, "Vis");
    btn.addEventListener("click", () => preview.replaceChildren(
      el("p", { class: "sub" }, `Screenshot ${fmtDateTime(s.screenshot.at)}`, s.screenshot.sha256 ? ` · SHA-256 ${s.screenshot.sha256}` : ""),
      el("div", { class: "evidence" }, el("img", { src: API + s.screenshot.url, alt: `DSB's side ${fmtDateTime(s.screenshot.at)}` }))));
    return tr(s, el("span", { class: "evidence" }, shot, btn));
  }
  return tr(s, shot);
}

function tr(s, shotCell) {
  return el("tr", {},
    el("td", {}, fmtDateTime(s.at)),
    el("td", { class: "num" }, s.rows),
    el("td", {}, s.dsb_updated ?? "–"),
    el("td", {}, s.html ? el("a", { href: API + s.html.url, target: "_blank", rel: "noopener" }, "Åbn") : "–"),
    el("td", {}, shotCell));
}
