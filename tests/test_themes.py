import json

from reeve import paths, report, themes
from reeve.hub import HubApi


def test_every_theme_defines_every_token():
    tokens = set(themes.themes()["age"]["colors"])
    for name, theme in themes.themes().items():
        assert tokens <= set(theme["colors"]), name
        assert theme["scheme"] in ("dark", "light") and theme["name"] and theme["description"]
    assert set(themes.themes()) == {"age", "dark", "dracula", "kitty"}


def test_css_carries_colors_resources_and_corners():
    css = themes.css(themes.themes()["kitty"], "rounded")
    assert "color-scheme: light" in css and "--accent: #e8508a" in css
    assert "--series-food: #e5484d" in css and "--series-gold: #d4a00f" in css   # game color, and a light-theme override
    assert "--radius: 10px" in css
    assert "--radius: 3px" in themes.css(themes.themes()["age"])


def test_unknown_choices_fall_back_to_defaults():
    cfg = {"appearance": {"theme": "nope", "corners": "wavy"}}
    assert themes.current(cfg)[0] == "age" and themes.corners(cfg) == "square"


def test_appearance_is_saved_at_once_and_reports_follow_it():
    api = HubApi()
    css = api.set_appearance("dracula", "rounded")
    assert "--accent: #bd93f9" in css and "--radius: 10px" in css
    saved = json.loads(paths.user_config_path().read_text(encoding="utf-8"))
    assert saved["appearance"] == {"theme": "dracula", "corners": "rounded"}
    assert report.look() == "dracula/rounded"
    html = report.render({"rows": [], "alerts": [], "frames": [], "ages": []}, "20260101-100000")
    assert 'content="dracula/rounded"' in html and "--accent: #bd93f9" in html


def test_hub_rewrites_a_report_drawn_with_another_look():
    folder = paths.sessions_dir() / "20260101-100000"
    folder.mkdir()
    lines = [{"t": 2.0 * i, "wall": "00:00:00", "values": {
        "clock": 10 + 2 * i, "pop": [8, 20], "idle": 0, "producing_villager": True,
        "food": 100, "wood": 50, "gold": 0, "stone": 0,
        "vil_food": 5, "vil_wood": 2, "vil_gold": 0, "vil_stone": 0}} for i in range(20)]
    (folder / "log.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    api = HubApi()
    api.report_url(folder.name)
    assert 'content="age/square"' in (folder / "report.html").read_text(encoding="utf-8")
    api.set_appearance("kitty", "square")
    api.report_url(folder.name)
    assert 'content="kitty/square"' in (folder / "report.html").read_text(encoding="utf-8")
