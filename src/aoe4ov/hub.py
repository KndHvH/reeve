"""The hub: match history, reports and settings in a native window.

pywebview renders assets/hub/hub.html with the system WebView2 and exposes
`HubApi` to its JavaScript (`window.pywebview.api`). The hub runs as its own
process, started from the tray, so it costs nothing during a match and never
competes with the overlay's Tk loop for the main thread.

Settings are saved as overrides of the shipped defaults (paths.save_overrides);
the overlay notices the file changed and reloads the rules and sounds.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import __version__
from .paths import DEFAULT_CONFIG, ROOT, data_dir, load_config, save_overrides, sessions_dir

HUB_HTML = ROOT / "assets" / "hub" / "hub.html"


def diff(defaults: dict, values: dict) -> dict:
    """Only what differs from the defaults (nested dicts compared key by key)."""
    out = {}
    for k, v in values.items():
        d = defaults.get(k)
        if isinstance(v, dict) and isinstance(d, dict):
            sub = diff(d, v)
            if sub:
                out[k] = sub
        elif v != d:
            out[k] = v
    return out


def match_summaries() -> list[dict]:
    """Every recorded match, newest first; summary.json is rebuilt when missing or stale."""
    from .report import write_summary

    out = []
    for s in sorted((p for p in sessions_dir().iterdir() if (p / "log.jsonl").exists()), reverse=True):
        summary, log = s / "summary.json", s / "log.jsonl"
        try:
            if summary.exists() and summary.stat().st_mtime >= log.stat().st_mtime:
                digest = json.loads(summary.read_text(encoding="utf-8"))
            else:
                digest = write_summary(s)
        except Exception:  # a broken log must not hide the others
            continue
        digest["has_report"] = (s / "report.html").exists()
        out.append(digest)
    return out


class HubApi:
    """Methods callable from the page as `await window.pywebview.api.<name>(...)`."""

    def __init__(self):
        self.window = None

    def version(self) -> str:
        return __version__

    def matches(self) -> list[dict]:
        return match_summaries()

    def open_report(self, session: str) -> bool:
        import webview

        from .report import write_report

        folder = sessions_dir() / session
        report = folder / "report.html"
        if not report.exists() or report.stat().st_mtime < (folder / "log.jsonl").stat().st_mtime:
            report = write_report(folder)
        webview.create_window(f"Match report – {session}", report.as_uri(), width=1280, height=900,
                              background_color="#0e1319")
        return True

    def settings(self) -> dict:
        from .sound import library

        return {"values": load_config(), "defaults": json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")),
                "sounds": library()}

    def save_settings(self, values: dict) -> dict:
        defaults = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        overrides = diff(defaults, values)
        save_overrides(overrides)
        return overrides

    def reset_settings(self) -> bool:
        save_overrides({})
        return True

    def preview_sound(self, name: str) -> bool:
        from .sound import play_file, sound_path

        path = sound_path(name)
        if path is None:
            return False
        play_file(path)
        return True

    def open_data_folder(self) -> bool:
        os.startfile(data_dir())
        return True


def main() -> None:
    import webview

    api = HubApi()
    api.window = webview.create_window("aoe4-overlay", HUB_HTML.as_uri(), js_api=api, width=1180, height=820,
                                       min_size=(900, 600), background_color="#0e1319")
    webview.start()


if __name__ == "__main__":
    main()
