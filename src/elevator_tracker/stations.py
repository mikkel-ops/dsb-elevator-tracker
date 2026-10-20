"""Turn DSB's free-text labels into stable asset ids.

"Århus H Spor 2" and "Århus spor 2" must map to the same elevator, otherwise
one outage looks like two. Labels are matched against known station names
(stations.json, built from Rejseplanen's GTFS by tools/build_stations.py),
falling back to a heuristic split; ALIASES covers what neither can.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path

STATIONS_PATH = Path(__file__).with_name("stations.json")

# Manual fixes, matched case-insensitively with whitespace collapsed.
# Add entries here as new variants show up on DSB's page.
LABEL_ALIASES = {
    # whole raw label -> rewritten label (applied first)
}
STATION_ALIASES = {
    # extracted station name -> canonical station name
    "århus": "Aarhus H",
    "århus h": "Aarhus H",
    "aarhus": "Aarhus H",
    "århus banegård": "Aarhus H",
    "aarhus banegård": "Aarhus H",
    "hovedbanegården": "København H",
    "høje tåstrup": "Høje Taastrup",
}

# Heuristic end of the station name when no known name matches.
_STATION_END = re.compile(
    r",|\s+(?:spor|st\.?|station|op|ned|ved|mod|til|elevator|elevatoren|lift)\b", re.IGNORECASE
)
_LEADING_ST = re.compile(r"^(?:st\.?|station)(?=\s|$|[,-])[\s,-]*", re.IGNORECASE)


@dataclass(frozen=True)
class Asset:
    asset_id: str  # "<station_slug>[:<location_slug>]"
    station: str  # canonical display name
    station_slug: str
    location: str  # the rest, e.g. "spor 3-4"


def slugify(text: str) -> str:
    text = text.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


@cache
def _known_names() -> list[str]:
    """Longest first, so "København H" wins over "København"."""
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))
    return sorted((s["name"] for s in stations.values()), key=len, reverse=True)


def _match_known(label: str) -> tuple[str, str] | None:
    low = label.lower()
    for name in _known_names():
        n = name.lower()
        if low.startswith(n) and (len(low) == len(n) or not low[len(n)].isalnum()):
            return name, _LEADING_ST.sub("", label[len(n):].lstrip(" ,-")).strip()
    return None


def _split(label: str) -> tuple[str, str]:
    m = _STATION_END.search(label)
    if not m or m.start() == 0:
        return label, ""
    return label[: m.start()].strip(), _LEADING_ST.sub("", label[m.start():].lstrip(" ,-")).strip()


def normalize(raw_label: str) -> Asset:
    label = re.sub(r"\s+", " ", raw_label).strip()
    label = LABEL_ALIASES.get(_key(label), label)
    station, location = _match_known(label) or _split(label)
    station = STATION_ALIASES.get(_key(station), station)
    station = station[:1].upper() + station[1:]
    slug, loc = slugify(station), slugify(location)
    return Asset(f"{slug}:{loc}" if loc else slug, station, slug, location)
