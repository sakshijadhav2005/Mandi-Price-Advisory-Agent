"""The vegetable list in reference.json and how questions are matched to a crop."""

from __future__ import annotations

import pytest

from app.ingestion.synthetic import PROFILES
from app.reference import detect_crop, load_reference
from app.translation.glossary import glossary


def test_every_crop_is_complete():
    crops = load_reference().crops
    assert len(crops) >= 25
    for c in crops.values():
        assert c.names.get("hi") and c.names.get("mr"), c.id
        assert c.agmarknet_commodity, c.id
        assert 0 < c.default_horizon_days <= c.max_hold_days, c.id
        assert c.id in PROFILES, f"{c.id} has no synthetic price profile"


def test_aliases_are_not_shared_between_crops():
    owner: dict[str, str] = {}
    for c in load_reference().crops.values():
        for alias in c.aliases:
            assert owner.setdefault(alias, c.id) == c.id, f"{alias!r} is an alias of {owner[alias]} and {c.id}"


def test_glossary_names_each_crop_in_every_language():
    g = glossary()
    for term in ("brinjal", "okra", "cauliflower", "spinach", "garlic"):
        assert set(g[term]) >= {"hi", "mr"}, term  # English is the key itself


@pytest.mark.parametrize(
    ("text", "crop"),
    [
        ("Should I sell my onions now?", "onion"),
        ("मी कांदा आता विकू की थांबू?", "onion"),
        ("aloo bechna hai", "potato"),
        # The longer, more specific name wins over a name it contains.
        ("shimla mirch ka bhav kya hai", "capsicum"),
        ("hari mirch bechu ya rukoo", "green_chilli"),
        ("patta gobi ka rate", "cabbage"),
        ("phool gobi bechu?", "cauliflower"),
        ("गोभी बेचूं?", "cauliflower"),
        ("पत्ता गोभी बेचूं?", "cabbage"),
        ("कोबीचा भाव काय आहे?", "cabbage"),
        ("फुलकोबी विकू का?", "cauliflower"),
        ("sweet potato price", "sweet_potato"),
        ("दुधी भोपळा विकू का", "bottle_gourd"),
        ("लाल भोपळा", "pumpkin"),
        ("cluster beans rate", "cluster_beans"),
        ("french beans rate", "beans"),
        ("माझ्याकडे 10 क्विंटल वांगी आहेत", "brinjal"),
        ("भेंडी आता विकावी का?", "okra"),
        ("कोथिंबीर भाव", "coriander"),
        ("लसूण साठवू का", "garlic"),
        ("आल्याचा भाव", "ginger"),
        ("हरी मटर कब बेचें", "green_peas"),
        ("मुळा विकू का", "radish"),
        # A crop name inside another word is not a mention: "-मुळे" means "because of".
        ("पावसामुळे भाव कमी आहे का? टोमॅटो", "tomato"),
        ("पावसामुळे भाव पडले", None),
        ("How should I store my produce?", None),
    ],
)
def test_detect_crop(text, crop):
    assert detect_crop(text) == crop
