"""Crop and market reference data, plus helpers for distances and name lookup."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import DATA_DIR


@dataclass(frozen=True)
class Market:
    id: str
    name: str
    lat: float
    lon: float
    names: dict[str, str] = field(default_factory=dict)
    district: str = ""

    def display(self, lang: str) -> str:
        return self.names.get(lang, self.name)


@dataclass(frozen=True)
class District:
    id: str
    name: str
    names: dict[str, str]
    state: str
    centre: dict
    market_ids: tuple[str, ...]

    def display(self, lang: str) -> str:
        return self.names.get(lang, self.name)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "names": self.names, "state": self.state, "centre": self.centre, "markets": list(self.market_ids)}


@dataclass(frozen=True)
class Crop:
    id: str
    name: str
    agmarknet_commodity: str
    aliases: tuple[str, ...]
    names: dict[str, str]
    storage_cost_per_qtl_day: float
    weight_loss_pct_per_day: float
    max_hold_days: int
    default_horizon_days: int

    def display(self, lang: str) -> str:
        return self.names.get(lang, self.name)


@dataclass(frozen=True)
class Scope:
    """The markets a farmer can sell at, and the point transport is measured from."""

    district: str
    lat: float
    lon: float
    market_ids: tuple[str, ...]
    location_known: bool


@dataclass(frozen=True)
class Reference:
    districts: dict[str, District]
    markets: dict[str, Market]
    crops: dict[str, Crop]
    transport: dict
    market_fees_pct: float
    nearby_radius_km: float = 60.0
    max_nearby_markets: int = 6

    @property
    def default_district(self) -> District:
        return next(iter(self.districts.values()))

    @property
    def district(self) -> dict:
        """Default district as a dict (name, state, centre)."""
        return self.default_district.as_dict()

    def nearest_district(self, lat: float, lon: float) -> District:
        return min(self.districts.values(), key=lambda d: haversine_km(lat, lon, d.centre["lat"], d.centre["lon"]))

    def scope(self, district: str | None = None, lat: float | None = None, lon: float | None = None) -> Scope:
        """Explicit district wins; else markets within the radius of the farmer; else the default district."""
        if district in self.districts:
            d = self.districts[district]
            if lat is None or lon is None:
                return Scope(d.id, d.centre["lat"], d.centre["lon"], d.market_ids, False)
            return Scope(d.id, lat, lon, d.market_ids, True)
        if lat is not None and lon is not None:
            ranked = sorted(self.markets.values(), key=lambda m: haversine_km(lat, lon, m.lat, m.lon))
            near = [m.id for m in ranked if haversine_km(lat, lon, m.lat, m.lon) <= self.nearby_radius_km][: self.max_nearby_markets]
            d = self.nearest_district(lat, lon)
            return Scope(d.id, lat, lon, tuple(near) or d.market_ids, True)
        d = self.default_district
        return Scope(d.id, d.centre["lat"], d.centre["lon"], d.market_ids, False)


@lru_cache
def load_reference() -> Reference:
    raw = json.loads((DATA_DIR / "reference.json").read_text(encoding="utf-8"))
    districts: dict[str, District] = {}
    markets: dict[str, Market] = {}
    for d in raw["districts"]:
        for m in d["markets"]:
            if m["id"] in markets:
                raise ValueError(f"duplicate market id {m['id']!r} in reference.json")
            markets[m["id"]] = Market(m["id"], m["name"], m["lat"], m["lon"], m.get("names", {}), d["id"])
        districts[d["id"]] = District(d["id"], d["name"], d.get("names", {}), d["state"], d["centre"], tuple(m["id"] for m in d["markets"]))
    crops = {
        c["id"]: Crop(
            id=c["id"],
            name=c["name"],
            agmarknet_commodity=c["agmarknet_commodity"],
            aliases=tuple(a.lower() for a in c["aliases"]),
            names=c.get("names", {}),
            storage_cost_per_qtl_day=c["storage_cost_per_qtl_day"],
            weight_loss_pct_per_day=c["weight_loss_pct_per_day"],
            max_hold_days=c["max_hold_days"],
            default_horizon_days=c["default_horizon_days"],
        )
        for c in raw["crops"]
    }
    return Reference(
        districts,
        markets,
        crops,
        raw["transport"],
        raw["market_fees_pct"],
        raw.get("nearby_radius_km", 60.0),
        raw.get("max_nearby_markets", 6),
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_TOKEN_RE = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def detect_crop(text: str) -> str | None:
    """Find a supported crop mentioned in free text (any supported language)."""
    toks = tokens(text)
    lowered = text.lower()
    for crop in load_reference().crops.values():
        for alias in crop.aliases:
            if alias in toks or (len(alias) > 3 and alias in lowered):
                return crop.id
    return None


def detect_district(text: str) -> str | None:
    lowered = text.lower()
    for d in load_reference().districts.values():
        if any(c and c.lower() in lowered for c in [d.id, d.name.lower(), *d.names.values()]):
            return d.id
    return None


def detect_market(text: str) -> str | None:
    lowered = text.lower()
    for m in load_reference().markets.values():
        candidates = [m.id, m.name.lower(), m.name.split()[0].lower(), *m.names.values()]
        if any(c and c.lower() in lowered for c in candidates):
            return m.id
    return None


_QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(quintals?|qtl|qtls|q\b|क्विंटल|tonnes?|tons?|टन|kg|kgs|किलो)", re.IGNORECASE
)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def detect_quantity_qtl(text: str) -> float | None:
    m = _QTY_RE.search(text.translate(_DEVANAGARI_DIGITS))
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).lower()
    if unit.startswith(("tonne", "ton", "टन")):
        return value * 10.0
    if unit.startswith(("kg", "किलो")):
        return value / 100.0
    return value
