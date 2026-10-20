"""Parse DSB's elevator/escalator page into structured rows.

The page is hand-edited rich text, so parsing is deliberately forgiving:
sections are recognised by their h3 heading, each outage is a <p> of the
form "<b>Label:</b> Status".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date

from bs4 import BeautifulSoup

ELEVATOR = "elevator"
ESCALATOR = "escalator"

# status_kind values
EXPECTED = "expected"  # "Forventes i drift den 24.10.26"
INDEFINITE = "indefinite"  # "på ubestemt tid", "indtil videre"
PERMANENT = "permanent"  # "Taget ud af drift permanent"
UNKNOWN = "unknown"

_DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")
_DANISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Row:
    asset_type: str
    raw_label: str
    status_text: str
    status_kind: str
    expected_date: str | None  # ISO date

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParseResult:
    rows: list[Row]
    sections_found: set[str]
    dsb_updated: str | None  # e.g. "20. okt. 13:33", kept verbatim


# Section headings. Older versions of the page used a bold <p> instead of
# <h3>, so paragraphs are checked against this too.
_HEADING_RE = re.compile(
    r"^(elevator|rulletrappe|kommende)\w*\b.*(ude af drift|projekt\w*)\s*:?$", re.IGNORECASE
)


def _heading(text: str) -> str | None:
    """Return 'elevator' / 'escalator' / 'other' for a heading, else None."""
    m = _HEADING_RE.match(text)
    if not m:
        return None
    word = m.group(1).lower()
    return {"elevator": ELEVATOR, "rulletrappe": ESCALATOR}.get(word, "other")


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
    if "forventes" in s:
        iso = parse_date(s)
        if iso:
            return EXPECTED, iso
    if "ubestemt" in s or "indtil videre" in s:
        return INDEFINITE, None
    return UNKNOWN, parse_date(s)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _split_label(p) -> tuple[str, str] | None:
    text = _clean(p.get_text(" "))
    if not text:
        return None
    if ":" in text:
        label, status = text.split(":", 1)
    else:
        b = p.find("b")
        if not b:
            return None
        label = _clean(b.get_text(" "))
        status = text[len(label):]
    label, status = _clean(label), _clean(status)
    if not label:
        return None
    return label, status


def parse(html: str) -> ParseResult:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("section", attrs={"aria-label": "Stations information"})
    if container is None:
        raise ParseError("container section not found - page layout changed?")

    rows: list[Row] = []
    sections: set[str] = set()
    current: str | None = None
    seen: set[tuple[str, str]] = set()

    for el in container.find_all(["h2", "h3", "h4", "p"]):
        text = _clean(el.get_text(" "))
        heading = _heading(text)
        if heading or el.name != "p":
            current = heading if heading in (ELEVATOR, ESCALATOR) else None
            if current:
                sections.add(current)
            continue
        if current is None:
            continue
        split = _split_label(el)
        if split is None:
            continue
        label, status = split
        key = (current, label.lower())
        if key in seen:  # DSB sometimes lists the same line twice
            continue
        seen.add(key)
        kind, expected = classify_status(status)
        rows.append(Row(current, label, status, kind, expected))

    return ParseResult(rows, sections, _dsb_updated(soup))


def _dsb_updated(soup) -> str | None:
    for div in soup.find_all("div", string="Opdateret"):
        nxt = div.find_next_sibling("div")
        if nxt:
            return _clean(nxt.get_text())
    return None
