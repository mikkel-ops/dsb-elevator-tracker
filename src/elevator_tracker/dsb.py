"""Fetch and parse DSB's elevator page.

The page is hand-edited rich text, so parsing is deliberately forgiving:
sections are recognised by their heading, each outage is a paragraph of the
form "<b>Label:</b> Status". Only the elevator section is read - escalators
and planned modernisations are ignored (the raw HTML is archived regardless).
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

URL = "https://www.dsb.dk/trafikinformation/elevatorer/"
USER_AGENT = "dsb-elevator-tracker/0.2 (+https://github.com/mikkel-ops/dsb-elevator-tracker)"

# status_kind values
EXPECTED = "expected"  # "Forventes i drift den 24.10.26"
INDEFINITE = "indefinite"  # "på ubestemt tid", "indtil videre"
PERMANENT = "permanent"  # "Taget ud af drift permanent"
UNKNOWN = "unknown"

_DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")
# Older versions of the page used a bold <p> instead of <h3> for headings,
# so every element is checked against this.
_HEADING_RE = re.compile(
    r"^(elevator|rulletrappe|kommende)\w*\b.*(ude af drift|projekt\w*)\s*:?$", re.IGNORECASE
)


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Row:
    raw_label: str
    status_text: str
    status_kind: str
    expected_date: str | None  # ISO date


@dataclass
class ParseResult:
    rows: list[Row]
    found_section: bool
    dsb_updated: str | None  # e.g. "20. okt. 13:33", kept verbatim


def fetch() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def parse_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = (int(g) for g in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mth, d).isoformat()
    except ValueError:
        return None


def classify_status(status: str) -> tuple[str, str | None]:
    s = status.lower()
    if "permanent" in s:
        return PERMANENT, None
    if "forventes" in s and (iso := parse_date(s)):
        return EXPECTED, iso
    if "ubestemt" in s or "indtil videre" in s:
        return INDEFINITE, None
    return UNKNOWN, parse_date(s)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _split_label(p, text: str) -> tuple[str, str] | None:
    if ":" in text:
        label, status = text.split(":", 1)
    elif b := p.find("b"):
        label = _clean(b.get_text(" "))
        status = text[len(label):]
    else:
        return None
    label, status = _clean(label), _clean(status)
    return (label, status) if label else None


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("section", attrs={"aria-label": "Stations information"})
    if container is None:
        raise ParseError("container section not found - page layout changed?")

    rows: list[Row] = []
    found = in_elevators = False
    seen: set[str] = set()
    for el in container.find_all(["h2", "h3", "h4", "p"]):
        text = _clean(el.get_text(" "))
        heading = _HEADING_RE.match(text)
        if heading or el.name != "p":
            in_elevators = bool(heading) and heading.group(1).lower() == "elevator"
            found |= in_elevators
            continue
        if not in_elevators or not text:
            continue
        split = _split_label(el, text)
        if split is None or split[0].lower() in seen:  # DSB sometimes repeats a line
            continue
        label, status = split
        seen.add(label.lower())
        rows.append(Row(label, status, *classify_status(status)))

    return ParseResult(rows, found, _dsb_updated(soup))


def _dsb_updated(soup) -> str | None:
    for div in soup.find_all("div", string="Opdateret"):
        if nxt := div.find_next_sibling("div"):
            return _clean(nxt.get_text())
    return None
