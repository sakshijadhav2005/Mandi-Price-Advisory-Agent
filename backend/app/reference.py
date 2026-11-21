"""Crop and market reference data, plus helpers for distances and name lookup."""

from __future__ import annotations

import difflib
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
    # Exact market names as Agmarknet / data.gov.in publish them (several spellings allowed).
    agmarknet_names: tuple[str, ...] = ()

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
    agmarknet_names: tuple[str, ...] = ()

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
    # Preferred Agmarknet varieties, best first. Rows of other varieties are averaged.
    agmarknet_varieties: tuple[str, ...] = ()
    # Other spellings Agmarknet has used for the same commodity ("Peas Wet" / "Green Peas").
    agmarknet_commodity_aliases: tuple[str, ...] = ()

    def display(self, lang: str) -> str:
        return self.names.get(lang, self.name)

    @property
    def agmarknet_commodities(self) -> tuple[str, ...]:
        return (self.agmarknet_commodity, *self.agmarknet_commodity_aliases)


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
    # Districts with hand-checked markets in reference.json (the pilot). Every other
    # district has a main market at its centre plus markets found in the Agmarknet feed.
    curated_districts: tuple[str, ...] = ()
    # (state key, Agmarknet market key) -> market id, for matching the price feed.
    agmarknet_index: dict[tuple[str, str], str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def default_district(self) -> District:
        return next(iter(self.districts.values()))

    @property
    def states(self) -> list[str]:
        return sorted({d.state for d in self.districts.values()})

    @property
    def curated_market_ids(self) -> list[str]:
        return [m for d in self.curated_districts for m in self.districts[d].market_ids]

    def market_by_agmarknet_name(self, name: str, state: str | None = None) -> Market | None:
        """Exact (case- and space-insensitive) match on a published Agmarknet market name.

        With `state`, only markets in that state match: "Aurangabad" is a market in
        Bihar and in Maharashtra. Without it, the first market with the name wins.
        """
        key = agmarknet_key(name)
        if not key:
            return None
        if state is not None:
            st = agmarknet_key(state)
            for (s_key, k), m_id in self.agmarknet_index.items():
                if k == key and _state_matches(st, self.districts[self.markets[m_id].district].state):
                    return self.markets[m_id]
            return None
        for (_st, k), m_id in self.agmarknet_index.items():
            if k == key:
                return self.markets[m_id]
        return None

    def district_by_agmarknet_name(self, state: str, name: str) -> District | None:
        """The district an Agmarknet row belongs to: same state, closest name spelling."""
        st = agmarknet_key(state)
        in_state = [d for d in self.districts.values() if _state_matches(st, d.state)]
        key = agmarknet_key(name)
        for d in in_state:
            if key in {agmarknet_key(n) for n in (*d.agmarknet_names, d.name)}:
                return d
        names = {agmarknet_key(d.name): d for d in in_state}
        close = difflib.get_close_matches(key, list(names), n=1, cutoff=0.8)
        return names[close[0]] if close else None

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


def _state_matches(state_key: str, state: str) -> bool:
    """Agmarknet spells some states differently ("Chattisgarh", "NCT of Delhi")."""
    ours = agmarknet_key(state)
    if not state_key:
        return False
    return state_key == ours or state_key.endswith(ours) or difflib.SequenceMatcher(None, state_key, ours).ratio() >= 0.85


def _main_market(d: District) -> Market:
    """The district's main market, at its centre, until the Agmarknet feed lists its markets.

    Its Agmarknet name is the district name, which is how Agmarknet usually names the
    market in the district headquarters, so real prices for it are matched directly.
    """
    return Market(
        f"{d.id}-market",
        f"{d.name} market",
        d.centre["lat"],
        d.centre["lon"],
        {"hi": f"{d.name} मंडी", "mr": f"{d.name} बाजार"},
        d.id,
        tuple(dict.fromkeys((d.name, *d.agmarknet_names))),
    )


def _discovered_markets() -> list[dict]:
    """Markets registered from the Agmarknet feed (table agmarknet_markets), if the table exists."""
    try:
        from sqlalchemy import inspect, select

        from app.db.models import AgmarknetMarket
        from app.db.session import get_engine

        engine = get_engine()
        if not inspect(engine).has_table(AgmarknetMarket.__tablename__):
            return []
        with engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(select(AgmarknetMarket.__table__))]
    except Exception:  # noqa: BLE001 - reference data must load even without a database
        return []


@lru_cache
def load_reference() -> Reference:
    """reference.json (pilot districts, crops, costs) + india_districts.json + discovered markets.

    Cached; call `load_reference.cache_clear()` after registering new markets.
    """
    raw = json.loads((DATA_DIR / "reference.json").read_text(encoding="utf-8"))
    districts: dict[str, District] = {}
    markets: dict[str, Market] = {}
    for d in raw["districts"]:
        for m in d["markets"]:
            if m["id"] in markets:
                raise ValueError(f"duplicate market id {m['id']!r} in reference.json")
            markets[m["id"]] = Market(
                m["id"], m["name"], m["lat"], m["lon"], m.get("names", {}), d["id"], tuple(m.get("agmarknet_names", [m["name"]]))
            )
        districts[d["id"]] = District(
            d["id"],
            d["name"],
            d.get("names", {}),
            d["state"],
            d["centre"],
            tuple(m["id"] for m in d["markets"]),
            tuple(d.get("agmarknet_names", [d["name"]])),
        )
    curated = tuple(districts)

    discovered: dict[str, list[dict]] = {}
    for row in _discovered_markets():
        discovered.setdefault(row["district"], []).append(row)
    india_path = DATA_DIR / "india_districts.json"
    if india_path.exists():
        for d in json.loads(india_path.read_text(encoding="utf-8")):
            if d["id"] in districts:
                continue  # the pilot entry in reference.json has the checked markets
            base = District(d["id"], d["name"], d.get("names", {}), d["state"], {"lat": d["lat"], "lon": d["lon"]}, (), (d["name"], *d.get("aliases", [])))
            main = _main_market(base)
            own = [main]
            for row in discovered.get(d["id"], []):
                if row["id"] in markets or row["id"] == main.id:
                    continue
                own.append(Market(row["id"], row["name"], row["lat"], row["lon"], {}, d["id"], (row["agmarknet_name"],)))
            for m in own:
                markets[m.id] = m
            districts[d["id"]] = District(
                base.id, base.name, base.names, base.state, base.centre, tuple(m.id for m in own), base.agmarknet_names
            )

    index: dict[tuple[str, str], str] = {}
    for m in markets.values():
        st = agmarknet_key(districts[m.district].state)
        for n in m.agmarknet_names or (m.name,):
            index.setdefault((st, agmarknet_key(n)), m.id)

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
            agmarknet_varieties=tuple(c.get("agmarknet_varieties", [])),
            agmarknet_commodity_aliases=tuple(c.get("agmarknet_commodity_aliases", [])),
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
        curated,
        index,
    )


def agmarknet_key(name: str) -> str:
    """Normalise a published market name: lower-case, no spaces, no punctuation."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_TOKEN_RE = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _starts_word(text: str, alias: str) -> bool:
    """`alias` occurs in `text` at the start of a word ("onions" has "onion").

    Devanagari vowel signs are not word characters for `\\b`, so the boundary is
    checked by hand: the alias must not follow a letter or vowel sign. This keeps
    a Marathi postposition such as "-मुळे" (because of) from reading as a crop.
    """
    start = text.find(alias)
    while start != -1:
        if start == 0 or not _TOKEN_RE.match(text[start - 1]):
            return True
        start = text.find(alias, start + 1)
    return False


def detect_crop(text: str) -> str | None:
    """Find a supported crop mentioned in free text (any supported language).

    The longest matching alias wins, so "shimla mirch" is capsicum rather than
    green chilli, "patta gobi" cabbage rather than cauliflower and "sweet potato"
    not potato. Short aliases (3 characters or fewer) must be a whole word.
    """
    toks = set(tokens(text))
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for crop in load_reference().crops.values():
        for alias in crop.aliases:
            if alias in toks or (len(alias) > 3 and _starts_word(lowered, alias)):
                if best is None or len(alias) > best[0]:
                    best = (len(alias), crop.id)
    return best[1] if best else None


# District and market names that are also everyday words in a farmer's question:
# "mandi" means market (and is a district in Himachal Pradesh), "mon" and "una" are
# districts too. They are never read as a place on their own.
_PLACE_STOPWORDS = {"mandi", "mon", "una", "market", "bazar", "bazaar"}


def _place_mentioned(text: str, name: str) -> bool:
    """`name` is a whole word in `text` (English), or starts a word (Devanagari, so
    "नाशिकला" still names Nashik)."""
    name = name.lower().strip()
    if not name or name in _PLACE_STOPWORDS:
        return False
    whole_word = name.isascii()
    start = text.find(name)
    while start != -1:
        before_ok = start == 0 or not _TOKEN_RE.match(text[start - 1])
        after = start + len(name)
        after_ok = not whole_word or after == len(text) or not _TOKEN_RE.match(text[after])
        if before_ok and after_ok:
            return True
        start = text.find(name, start + 1)
    return False


def _without_crop_names(text: str) -> str:
    """Remove multi-word crop names first: "shimla mirch" is capsicum, not Shimla district."""
    lowered = text.lower()
    for crop in load_reference().crops.values():
        for alias in crop.aliases:
            if " " in alias:
                lowered = lowered.replace(alias, " ")
    return lowered


def _best_place(text: str, candidates, preferred=lambda _id: False) -> str | None:
    """Longest name mentioned wins; on a tie, a place `preferred` says yes to."""
    best: tuple[int, bool, str] | None = None
    for place_id, names in candidates:
        for n in names:
            if n and _place_mentioned(text, n):
                score = (len(n), bool(preferred(place_id)), place_id)
                if best is None or score[:2] > best[:2]:
                    best = score
    return best[2] if best else None


def detect_district(text: str, prefer_state: str | None = None) -> str | None:
    """A district named in the question (any in India), longest name first.

    Several states have a district of the same name ("Aurangabad" in Bihar, and the
    old name of Chhatrapati Sambhajinagar in Maharashtra); the farmer's own state wins.
    """
    lowered = _without_crop_names(text)
    ref = load_reference()
    return _best_place(
        lowered,
        ((d.id, (d.name, *d.names.values(), *d.agmarknet_names)) for d in ref.districts.values()),
        lambda d_id: prefer_state is not None and ref.districts[d_id].state == prefer_state,
    )


def detect_market(text: str) -> str | None:
    lowered = _without_crop_names(text)
    ref = load_reference()
    return _best_place(
        lowered,
        ((m.id, (m.name, m.name.split()[0], *m.names.values(), *m.agmarknet_names)) for m in ref.markets.values()),
    )


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


def locked_district() -> str | None:
    """The district this deployment is locked to (LOCKED_DISTRICT), or None when it serves all."""
    from app.config import get_settings

    wanted = get_settings().locked_district.strip().lower()
    if not wanted:
        return None
    if wanted not in load_reference().districts:
        raise ValueError(f"LOCKED_DISTRICT={wanted!r} is not a known district id")
    return wanted


def effective_district(requested: str | None) -> str | None:
    """The district to use: the locked one when the deployment is locked, else the request's."""
    return locked_district() or requested

