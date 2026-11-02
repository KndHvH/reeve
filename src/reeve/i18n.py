"""Interface language: English (the source) or a translation.

Every text the player sees is written in English in the code and wrapped in
`t("...")` (or `tn(one, many, n)` for a count); a translation is a JSON file
in assets/i18n/ mapping the English text to the translated one, shared by
Python, the hub and the match reports. A text missing from it stays in
English. Placeholders are `{name}`, filled the same way in Python and in
JavaScript. Developer tools (CLI, debug view, logs) stay in English.

The setting `general.language` is "auto" (the Windows display language when
there is a translation for it, else English), "en" or a translation's code.
"""

from __future__ import annotations

import ctypes
import json

from .paths import ROOT

CATALOGS = ROOT / "assets" / "i18n"
# Each language in its own name, as the language picker shows it.
LANGUAGES = {"en": "English", "pt-BR": "Português (Brasil)"}
WINDOWS = {0x16: "pt-BR"}   # Windows primary language id -> translation

_lang: str | None = None
_strings: dict[str, str] = {}


def system_language() -> str:
    """The Windows display language, when there is a translation for it."""
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return WINDOWS.get(langid & 0x3FF, "en")


def resolve(setting: str | None) -> str:
    if setting in LANGUAGES:
        return setting
    return system_language()


def catalog(lang: str) -> dict[str, str]:
    if lang == "en":
        return {}
    try:
        return json.loads((CATALOGS / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_language(config: dict | None = None) -> str:
    """Applies the language setting of `config` (the saved settings when
    omitted); returns the language in use."""
    global _lang, _strings
    if config is None:
        from .paths import load_config

        config = load_config()
    lang = resolve((config.get("general") or {}).get("language"))
    if lang != _lang:
        _lang, _strings = lang, catalog(lang)
    return lang


def current() -> str:
    return _lang or set_language()


def strings() -> dict[str, str]:
    """The current translation, for the hub and the reports' JavaScript."""
    current()
    return _strings


def t(text: str, **values) -> str:
    current()
    out = _strings.get(text, text)
    return out.format(**values) if values else out


def N_(text: str) -> str:
    """Marks a text translated later, where it is shown (a label kept in a
    table); returns it unchanged. Lets the test of the translations find it."""
    return text


def tn(one: str, many: str, n: int, **values) -> str:
    """`one` for a count of 1, else `many`; `n` is a placeholder too."""
    return t(one if n == 1 else many, n=n, **values)
