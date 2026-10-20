"""Turn DSB's free-text labels into stable asset ids.

"Århus H Spor 2 Ned" and "Århus spor 2 ned" must map to the same asset,
otherwise one outage looks like two. Automatic normalisation handles case,
whitespace and punctuation; aliases.yaml handles everything else and is
meant to be edited by hand as new variants show up.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ALIASES_PATH = Path(__file__).with_name("aliases.yaml")
STATIONS_PATH = Path(__file__).with_name("station_names.json")  # tools/build_stations.py

# Where the station name ends and the platform/location description begins.
_STATION_END = re.compile(
    r",|\s+(?:spor|st\.|station|op|ned|ved|mod|til|elevator|elevatoren|lift)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Asset:
    asset_id: str
    station: str  # canonical display name
    station_slug: str
    location: str  # the rest, e.g. "spor 3-4"


def slugify(text: str) -> str:
    text = text.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


@lru_cache(maxsize=1)
def _aliases() -> dict:
    data = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return {
        "labels": {_key(k): v for k, v in (data.get("labels") or {}).items()},
        "stations": {_key(k): v for k, v in (data.get("stations") or {}).items()},
    }


@lru_cache(maxsize=1)
def _known_stations() -> list[str]:
    """Known station names, longest first, so "København H" beats "København"."""
    if not STATIONS_PATH.exists():
        return []
    return sorted(json.loads(STATIONS_PATH.read_text(encoding="utf-8")), key=len, reverse=True)


_LEADING_ST = re.compile(r"^(?:st\.?|station)(?=\s|$|[,-])[\s,-]*", re.IGNORECASE)


def _match_known(label: str) -> tuple[str, str] | None:
    low = label.lower()
    for name in _known_stations():
        n = name.lower()
        if low.startswith(n) and (len(low) == len(n) or not low[len(n)].isalnum()):
            rest = label[len(n):].lstrip(" ,-")
            return name, _LEADING_ST.sub("", rest).strip()
    return None


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _split(label: str) -> tuple[str, str]:
    m = _STATION_END.search(label)
    if not m or m.start() == 0:
        return label.strip(), ""
    return label[: m.start()].strip(), label[m.start():].lstrip(" ,").strip()


def normalize(asset_type: str, raw_label: str) -> Asset:
    aliases = _aliases()
    label = re.sub(r"\s+", " ", raw_label).strip()
    label = aliases["labels"].get(_key(label), label)

    station, location = _match_known(label) or _split(label)
    station = aliases["stations"].get(_key(station), station)
    station = station[:1].upper() + station[1:]

    station_slug = slugify(station)
    loc_slug = slugify(location)
    asset_id = f"{asset_type}:{station_slug}" + (f":{loc_slug}" if loc_slug else "")
    return Asset(asset_id, station, station_slug, location)
