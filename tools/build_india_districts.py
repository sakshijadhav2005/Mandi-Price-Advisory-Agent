"""Build backend/data/india_districts.json: every district of India with its state and centre.

Source: INDIA_DISTRICTS.geojson from https://github.com/datta07/INDIAN-SHAPEFILES
(MIT licence; district boundaries with current districts, e.g. Alluri Sitharama Raju).
The centre is the area-weighted centroid of the district's polygons; it is used to
estimate transport distance and to find the farmer's nearest district from GPS.

    curl -L -o INDIA_DISTRICTS.geojson https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_DISTRICTS.geojson
    python tools/build_india_districts.py INDIA_DISTRICTS.geojson

Ids are a slug of the district name ("nashik"); a name used in two states gets
the state code appended ("aurangabad-mh", "aurangabad-br"). Ids already in
reference.json keep working because the pilot districts slug to the same id.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "india_districts.json"

# Short codes for ids of districts whose name repeats across states.
STATE_CODES = {
    "Andaman and Nicobar Islands": "an", "Andhra Pradesh": "ap", "Arunachal Pradesh": "ar", "Assam": "as", "Bihar": "br",
    "Chandigarh": "ch", "Chhattisgarh": "cg", "Dadra and Nagar Haveli and Daman and Diu": "dn", "Delhi": "dl", "Goa": "ga",
    "Gujarat": "gj", "Haryana": "hr", "Himachal Pradesh": "hp", "Jammu and Kashmir": "jk", "Jharkhand": "jh", "Karnataka": "ka",
    "Kerala": "kl", "Ladakh": "la", "Lakshadweep": "ld", "Madhya Pradesh": "mp", "Maharashtra": "mh", "Manipur": "mn",
    "Meghalaya": "ml", "Mizoram": "mz", "Nagaland": "nl", "Odisha": "od", "Puducherry": "py", "Punjab": "pb", "Rajasthan": "rj",
    "Sikkim": "sk", "Tamil Nadu": "tn", "Telangana": "ts", "Tripura": "tr", "Uttar Pradesh": "up", "Uttarakhand": "uk",
    "West Bengal": "wb",
}

# Spellings in the boundary file -> the usual state name.
STATE_FIX = {
    "andaman & nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "jammu & kashmir": "Jammu and Kashmir",
    "nct of delhi": "Delhi",
    "the dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "uttaranchal": "Uttarakhand",
    "chhatisgarh": "Chhattisgarh",
}

# The file stores long vowels as stray symbols: Bengal#ru = Bengaluru, Barddham>n,
# Medin|pur, Dehrad@n, B\dar. They become plain vowels.
CHAR_FIX = str.maketrans({">": "a", "|": "i", "#": "u", "@": "u", "\\": "i", "_": "-"})

# Karnataka names cut off at the first such symbol ("B", "H", "Kol"), by district code.
# Two different districts both became "H"; their codes and positions tell them apart.
CODE_FIX = {
    "0556": "Bagalkote", "0555": "Belagavi", "0565": "Ballari", "0578": "Chamarajanagar",
    "0582": "Chikkaballapura", "0567": "Davanagere", "0562": "Dharwad", "0564": "Haveri",
    "0574": "Hassan", "0581": "Kolar", "0580": "Yadgir", "0584": "Ramanagara",
}

# Other corrections: (state, name after CHAR_FIX and title case) -> correct name.
NAME_FIX = {
    ("Maharashtra", "Raigarh"): "Raigad",  # Raigarh is in Chhattisgarh
    ("Arunachal Pradesh", "Anjaw"): "Anjaw",
    ("West Bengal", "Alipur Duar"): "Alipurduar",
    ("West Bengal", "Haora"): "Howrah",
    ("West Bengal", "South 24parganas"): "South 24 Parganas",
    ("West Bengal", "North 24parganas"): "North 24 Parganas",
    ("Karnataka", "Bengaluru (rural)"): "Bengaluru Rural",
    ("Karnataka", "Bengaluru (urban)"): "Bengaluru Urban",
    ("Telangana", "Medchal-malkajgiri"): "Medchal-Malkajgiri",
    ("Andhra Pradesh", "Ntr"): "NTR",
    ("Andhra Pradesh", "Ysr Kadapa"): "YSR Kadapa",
    ("Punjab", "Sas Nagar (sahibzada Ajit Singh Nagar)"): "SAS Nagar",
}

# Delhi's districts are named by direction only ("West"); add the city so they read as places.
DELHI_DIRECTIONS = {"north", "south", "east", "west", "central", "north east", "north west", "south east", "south west", "new"}

# Older or everyday names that farmers and Agmarknet still use (state, name) -> aliases.
ALIASES = {
    ("Maharashtra", "Chhatrapati Sambhajinagar"): ["Aurangabad"],
    ("Maharashtra", "Dharashiv"): ["Osmanabad"],
    ("Maharashtra", "Ahmednagar"): ["Ahilyanagar", "Ahmadnagar"],
    ("Maharashtra", "Beed"): ["Bid"],
    ("Maharashtra", "Gondia"): ["Gondiya"],
    ("Maharashtra", "Mumbai"): ["Mumbai City", "Bombay"],
    ("Uttar Pradesh", "Prayagraj"): ["Allahabad"],
    ("Uttar Pradesh", "Ayodhya"): ["Faizabad"],
    ("Uttar Pradesh", "Bhadohi"): ["Sant Ravidas Nagar"],
    ("Haryana", "Gurugram"): ["Gurgaon"],
    ("Haryana", "Nuh"): ["Mewat"],
    ("Karnataka", "Bengaluru Urban"): ["Bangalore", "Bengaluru", "Bangalore Urban"],
    ("Karnataka", "Bengaluru Rural"): ["Bangalore Rural"],
    ("Karnataka", "Belagavi"): ["Belgaum"],
    ("Karnataka", "Mysuru"): ["Mysore"],
    ("Karnataka", "Kalaburagi"): ["Gulbarga"],
    ("Karnataka", "Vijayapura"): ["Bijapur"],
    ("Karnataka", "Shivamogga"): ["Shimoga"],
    ("Karnataka", "Ballari"): ["Bellary"],
    ("Karnataka", "Tumakuru"): ["Tumkur"],
    ("Karnataka", "Chikkamagaluru"): ["Chikmagalur"],
    ("Karnataka", "Bagalkote"): ["Bagalkot"],
    ("Karnataka", "Davanagere"): ["Davangere"],
    ("Madhya Pradesh", "Narmadapuram"): ["Hoshangabad"],
    ("Gujarat", "Ahmadabad"): ["Ahmedabad"],
    ("Gujarat", "Kachchh"): ["Kutch"],
    ("Gujarat", "Panch Mahals"): ["Panchmahal"],
    ("Odisha", "Balasore"): ["Baleshwar"],
    ("Tamil Nadu", "Thoothukudi"): ["Tuticorin"],
    ("Tamil Nadu", "Kanchipuram"): ["Kancheepuram"],
    ("Rajasthan", "Ganganagar"): ["Sri Ganganagar"],
    ("West Bengal", "Hugli"): ["Hooghly"],
    ("West Bengal", "North Twenty-four Parganas"): ["North 24 Parganas"],
    ("West Bengal", "Koch Bihar"): ["Cooch Behar"],
    ("West Bengal", "Darjiling"): ["Darjeeling"],
    ("West Bengal", "Maldah"): ["Malda"],
    ("West Bengal", "Purba Medinipur"): ["East Midnapore"],
    ("West Bengal", "Paschim Medinipur"): ["West Midnapore"],
    ("West Bengal", "Purba Barddhaman"): ["Purba Bardhaman", "Burdwan"],
    ("West Bengal", "Paschim Barddhaman"): ["Paschim Bardhaman"],
    ("Andhra Pradesh", "Sri Potti Sriramulu Nellore"): ["Nellore"],
    ("Andhra Pradesh", "YSR Kadapa"): ["Kadapa", "Cuddapah"],
    ("Punjab", "SAS Nagar"): ["Mohali"],
    ("Uttarakhand", "Dehradun"): ["Dehra Dun"],
}

SMALL = {"and", "of", "the", "de", "da"}


def title(name: str) -> str:
    words = re.sub(r"\s+", " ", name.strip()).lower().split(" ")
    return " ".join(w if (i and w in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words)).replace("&", "and")


def clean_name(state: str, raw: str, code: str) -> str:
    if state == "Karnataka" and code in CODE_FIX:
        return CODE_FIX[code]
    name = title(raw.translate(CHAR_FIX))
    name = NAME_FIX.get((state, name), name)
    if state == "Delhi" and name.lower() in DELHI_DIRECTIONS:
        name = f"{name} Delhi"
    return name


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def ring_area_centroid(ring: list) -> tuple[float, float, float]:
    """Signed area and centroid of a polygon ring (shoelace formula, lon/lat degrees)."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    a /= 2
    if abs(a) < 1e-12:
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a), cx / (6 * a), cy / (6 * a)


def polygons(geom: dict) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def main(path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])  # area, sum(x*a), sum(y*a)
    for f in data["features"]:
        p = f["properties"]
        state_raw, name_raw = (p.get("state") or "").strip(), (p.get("district") or "").strip()
        # Skipped: disputed border slivers (no state) and one "ISLAND" sliver filed under
        # "GUJARAT and DNH & DD ISLANDS", and Delhi's "NAZUL" (government land); none is a district.
        if not state_raw or not name_raw or not f.get("geometry") or "dnh" in state_raw.lower() or name_raw.upper() == "NAZUL":
            continue
        state = STATE_FIX.get(state_raw.lower(), title(state_raw))
        key = (state, clean_name(state, name_raw, str(p.get("dist_code") or "")))
        for poly in polygons(f["geometry"]):
            area, x, y = ring_area_centroid([tuple(pt[:2]) for pt in poly[0]])  # outer ring
            a = acc[key]
            a[0] += area
            a[1] += x * area
            a[2] += y * area

    by_slug: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for state, name in acc:
        by_slug[slug(name)].append((state, name))

    unknown_states = sorted({s for s, _ in acc} - set(STATE_CODES))
    if unknown_states:
        raise SystemExit(f"add these states to STATE_CODES / STATE_FIX: {unknown_states}")

    out = []
    for (state, name), (area, sx, sy) in acc.items():
        if area <= 0:
            continue
        base = slug(name)
        did = base if len(by_slug[base]) == 1 else f"{base}-{STATE_CODES[state]}"
        entry = {"id": did, "name": name, "state": state, "lat": round(sy / area, 4), "lon": round(sx / area, 4)}
        if (state, name) in ALIASES:
            entry["aliases"] = ALIASES[(state, name)]
        out.append(entry)
    out.sort(key=lambda d: (d["state"], d["name"]))
    ids = [d["id"] for d in out]
    assert len(ids) == len(set(ids)), "duplicate district ids"
    OUT.write_text(
        "[\n" + ",\n".join("  " + json.dumps(d, ensure_ascii=False) for d in out) + "\n]\n",
        encoding="utf-8",
    )
    print(f"{len(out)} districts in {len({d['state'] for d in out})} states/UTs -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
