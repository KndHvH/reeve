import ast
import json
import re
from pathlib import Path

import pytest

from reeve import i18n
from reeve.paths import ROOT

SRC = ROOT / "src" / "reeve"
HUB = ROOT / "assets" / "hub" / "hub.html"
JS_CALL = re.compile(r'\b(?:tr|N_)\("((?:[^"\\]|\\.)*)"')
JS_PLURAL = re.compile(r'\btrn\("((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"')
TEMPLATE_MARK = re.compile(r"\{\{t:(.+?)\}\}")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Texts looked up by a name the code holds: resources and the icons named after them.
DYNAMIC = {"food", "wood", "gold", "stone", "builder", "villager", "pop"}


def _python_texts() -> set[str]:
    out = set()
    for path in SRC.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "tn", "N_"):
                n = 2 if node.func.id == "tn" else 1
                out |= {a.value for a in node.args[:n] if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return out


def _page_texts() -> set[str]:
    out = set()
    for text in (HUB.read_text(encoding="utf-8"), (SRC / "report.py").read_text(encoding="utf-8")):
        out |= {json.loads(f'"{m}"') for m in JS_CALL.findall(text)}
        out |= {json.loads(f'"{m}"') for pair in JS_PLURAL.findall(text) for m in pair}
        out |= set(TEMPLATE_MARK.findall(text))
    return out


def all_texts() -> set[str]:
    from reeve.themes import themes
    return _python_texts() | _page_texts() | DYNAMIC | {th["description"] for th in themes().values()}


@pytest.mark.parametrize("lang", [code for code in i18n.LANGUAGES if code != "en"])
def test_every_text_is_translated(lang):
    cat = i18n.catalog(lang)
    missing = sorted(all_texts() - cat.keys())
    assert not missing, f"{len(missing)} texts missing from {lang}.json:\n" + "\n".join(missing)


@pytest.mark.parametrize("lang", [code for code in i18n.LANGUAGES if code != "en"])
def test_translations_keep_the_placeholders(lang):
    wrong = [k for k, v in i18n.catalog(lang).items() if set(PLACEHOLDER.findall(k)) != set(PLACEHOLDER.findall(v))]
    assert not wrong, wrong


@pytest.mark.parametrize("lang", [code for code in i18n.LANGUAGES if code != "en"])
def test_no_stale_translations(lang):
    """A text removed from the code leaves the translation too."""
    stale = sorted(i18n.catalog(lang).keys() - all_texts())
    assert not stale, stale


def test_auto_follows_windows_and_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "pt-BR")
    assert i18n.set_language({"general": {"language": "auto"}}) == "pt-BR"
    assert i18n.t("Town center idle: queue a villager") != "Town center idle: queue a villager"
    assert i18n.set_language({"general": {"language": "en"}}) == "en"
    assert i18n.t("Town center idle: queue a villager") == "Town center idle: queue a villager"
    assert i18n.tn("{n} idle villager", "{n} idle villagers", 3) == "3 idle villagers"


def test_alerts_and_build_instructions_follow_the_language():
    from reeve.builds import describe

    i18n.set_language({"general": {"language": "pt-BR"}})
    text = describe(("move", 2, "wood", "food"))
    assert "2" in text and i18n.t("wood") in text and i18n.t("food") in text and "Move" not in text


def test_report_is_written_in_the_language():
    from reeve import report

    i18n.set_language({"general": {"language": "pt-BR"}})
    page = report.render({"rows": [], "alerts": [], "frames": [], "ages": []}, "20260101-100000")
    assert '<html lang="pt-BR">' in page and "{{t:" not in page
    assert i18n.t("Match report") in page and report.look().endswith("/pt-BR")


def test_hub_and_reports_share_the_catalog_file():
    assert Path(i18n.CATALOGS / "pt-BR.json").exists()
