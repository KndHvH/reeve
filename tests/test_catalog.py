import json

from reeve import catalog
from reeve.builds import Build, BuildTracker

GUIDES_NAMES = [  # what aoe4guides' overlay format writes as "civilization"
    "English", "French", "Rus", "Malians", "Delhi Sultanate", "Holy Roman Empire", "Abbasid Dynasty", "Ottomans",
    "Chinese", "Mongols", "Byzantines", "Japanese", "Ayyubids", "Jeanne d'Arc", "Zhu Xi's Legacy",
    "Order of the Dragon", "House of Lancaster", "Knights Templar", "Golden Horde", "Macedonian Dynasty",
    "Sengoku Daimyo", "Tughlaq Dynasty", "Jin Dynasty", "Vikings", "Scots",
]


def test_every_aoe4guides_civilization_has_an_entry_and_a_flag():
    for name in GUIDES_NAMES:
        civ = catalog.find(name)
        assert civ is not None, name
        assert catalog.flag_file(name) is not None, name


def test_find_takes_any_of_a_civilizations_names():
    assert catalog.find("MAL")["abbr"] == catalog.find("malians")["abbr"] == catalog.find("ma")["abbr"] == "ma"
    assert catalog.find("Holy Roman Empire")["slug"] == "hre"
    assert catalog.find("Any Civilization") is None
    assert catalog.find("") is None and catalog.find(None) is None


def test_villager_time_comes_from_the_catalog_and_never_exceeds_the_default():
    assert catalog.villager_s("French", 20) == 19
    assert catalog.villager_s("Unknown", 20) == 20

    def tracker(civ):
        return BuildTracker(Build(id="x", name="x", civ=civ, author="", source="", steps=[]))

    assert tracker("French").villager_s == 19
    assert tracker("Golden Horde").villager_s == 20   # slower: the estimate keeps its upper bound
    assert tracker("").villager_s == 20


def _fake_site(calls, broken=()):
    unit = {"__version__": "1.2.3", "data": [
        {"id": "villager", "icon": "https://data.aoe4world.com/images/units/villager.png",
         "variations": [{"id": "villager-1", "icon": "https://data.aoe4world.com/images/units/villager.png"}]},
        {"id": "donso", "icon": "https://data.aoe4world.com/images/units/donso-1.png"}]}

    def get(url):
        calls.append(url)
        if url in broken:
            raise OSError("offline")
        if url.endswith(".json"):
            return json.dumps(unit if "/units/" in url else {"__version__": "1.2.3", "data": []}).encode()
        return b"png:" + url.encode()
    return get


def test_download_stores_the_civilizations_data_and_icons_once():
    calls = []
    mali = catalog.find("Malians")
    assert not catalog.has(mali)
    assert catalog.download(mali, _fake_site(calls))
    assert catalog.has(mali)
    assert [u.rsplit("/", 1)[-1] for u in calls if u.endswith(".json")] == ["malians-optimized.json"] * 4
    icons = [u for u in calls if u.endswith(".png")]
    assert sorted(icons) == ["https://data.aoe4world.com/images/units/donso-1.png",
                             "https://data.aoe4world.com/images/units/villager.png"]
    assert catalog.icon_file(icons[0], "units").read_bytes().startswith(b"png:")
    assert [u["id"] for u in catalog.items(mali, "units")] == ["villager", "donso"]

    calls.clear()
    assert catalog.download(mali, _fake_site(calls)) and calls == []        # already complete

    calls.clear()
    eng = catalog.find("English")
    assert catalog.download(eng, _fake_site(calls))
    assert not [u for u in calls if u.endswith(".png")]                     # icons shared with Malians


def test_a_failed_icon_leaves_the_civilization_to_be_completed_later():
    calls = []
    villager = "https://data.aoe4world.com/images/units/villager.png"
    assert not catalog.download(catalog.find("French"), _fake_site(calls, broken={villager}))
    assert not catalog.has(catalog.find("French"))
    calls.clear()
    assert catalog.download(catalog.find("French"), _fake_site(calls))
    assert [u for u in calls if u.endswith(".png")] == [villager]           # only what was missing


def test_ensure_never_raises_without_network():
    def offline(url):
        raise OSError("no network")

    assert catalog.ensure("Malians", offline) is False
    assert catalog.ensure("Any Civilization", offline) is False
