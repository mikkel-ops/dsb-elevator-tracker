// Shared helpers. All API data is rendered with textContent (never innerHTML),
// since labels come straight from DSB's free text.

export const API = location.port === "8080" ? "http://localhost:8000" : "";

export async function api(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

/** el("td", {class: "num"}, "text", childNode, ...) */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const nf = new Intl.NumberFormat("da-DK", { maximumFractionDigits: 1 });
export const num = (n) => (n === null || n === undefined ? "–" : nf.format(n));

const dateFmt = new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "short", year: "numeric", timeZone: "Europe/Copenhagen" });
const dateTimeFmt = new Intl.DateTimeFormat("da-DK", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Copenhagen" });
export const fmtDate = (iso) => (iso ? dateFmt.format(new Date(iso.length === 10 ? iso + "T12:00:00" : iso)) : "–");
export const fmtDateTime = (iso) => (iso ? dateTimeFmt.format(new Date(iso)) : "–");

/** "3 timer", "12 dage"; prefixed "mindst" when the start is unknown. */
export function duration(days, lowerBound = false) {
  let s;
  if (days < 1) {
    const h = Math.max(1, Math.round(days * 24));
    s = `${h} ${h === 1 ? "time" : "timer"}`;
  } else {
    const d = Math.round(days);
    s = `${d} ${d === 1 ? "dag" : "dage"}`;
  }
  return lowerBound ? `mindst ${s}` : s;
}

export const TYPE = { elevator: "Elevator", escalator: "Rulletrappe" };

export function statusCell(inc) {
  if (inc.overdue) return el("span", { class: "status-critical" }, "Lovet dato overskredet");
  if (inc.status_kind === "permanent") return "Taget ud af drift permanent";
  if (inc.status_kind === "indefinite") return "Ubestemt tid";
  return "";
}

/** Links to the screenshot + raw HTML of DSB's page at a given moment. */
export async function evidenceLinks(at, label) {
  const box = el("span", { class: "evidence" }, el("span", { class: "muted" }, `${label}: henter…`));
  try {
    const ev = await api(`/api/evidence?at=${encodeURIComponent(at)}`);
    const links = [];
    if (ev.screenshot) links.push(el("a", { href: API + ev.screenshot.url, target: "_blank", rel: "noopener" }, `Screenshot (${fmtDateTime(ev.screenshot.at)})`));
    if (ev.html) links.push(el("a", { href: API + ev.html.url, target: "_blank", rel: "noopener" }, "Rå HTML"));
    box.replaceChildren(el("span", {}, `${label}: `), ...(links.length ? links : [el("span", { class: "muted" }, "ingen dokumentation")]));
  } catch {
    box.replaceChildren(el("span", { class: "muted" }, `${label}: kunne ikke hentes`));
  }
  return box;
}

export function showError(container, err) {
  container.replaceChildren(el("p", { class: "empty" }, "Data kunne ikke hentes lige nu. Prøv igen om lidt."));
  console.error(err);
}
