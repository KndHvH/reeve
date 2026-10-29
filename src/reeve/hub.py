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
import threading
from pathlib import Path

from .paths import (DEFAULT_CONFIG, ROOT, data_dir, load_config, save_overrides, sessions_dir,
                    user_config_path, user_sounds_dir)

HUB_HTML = ROOT / "assets" / "hub" / "hub.html"
APP_ICON = ROOT / "assets" / "app.ico"   # the tray icon (tray._tray_image), all sizes


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
        if not digest.get("duration"):   # no game time read: not a match
            continue
        digest["has_report"] = (s / "report.html").exists()
        out.append(digest)
    return out


def _code_mtime(module) -> float:
    """When a module's code last changed: its source file, or the app's own
    executable once packaged (the source is not on disk there)."""
    import sys

    for p in (getattr(module, "__file__", None), sys.executable if getattr(sys, "frozen", False) else None):
        try:
            return Path(p).stat().st_mtime
        except (OSError, TypeError):
            continue
    return 0.0


def _report_look(report: Path) -> str | None:
    """The theme/corners a report was written with (its reeve-look meta tag)."""
    import re

    with open(report, encoding="utf-8", errors="ignore") as f:
        m = re.search(r'name="reeve-look" content="([^"]*)"', f.read(1024))
    return m.group(1) if m else None


def _user_sounds() -> list[str]:
    return sorted(p.stem for p in user_sounds_dir().glob("*.wav"))


class HubApi:
    """Methods callable from the page as `await window.pywebview.api.<name>(...)`."""

    def __init__(self):
        # Private on purpose: pywebview walks the public attributes of js_api to
        # expose them, and a Window holds native WinForms objects whose
        # references loop forever (RecursionError on SyncRoot/DefaultFont).
        self._window = None

    def version(self) -> str:
        from .version import shown

        return shown()

    def matches(self) -> list[dict]:
        return match_summaries()

    def report_url(self, session: str) -> str:
        """The report's file URL, shown inside the hub. Rebuilt when the log or
        the report code is newer, so layout changes reach older matches too."""
        from . import report as report_module
        from .report import write_report

        folder = sessions_dir() / session
        report = folder / "report.html"
        newest = max((folder / "log.jsonl").stat().st_mtime, _code_mtime(report_module))
        if (not report.exists() or report.stat().st_mtime < newest
                or _report_look(report) != report_module.look()):   # theme or corners changed
            report = write_report(folder)
        return report.as_uri()

    def open_report_external(self, session: str) -> bool:
        """The same file in the default browser, e.g. to share or print it."""
        os.startfile(sessions_dir() / session / "report.html")
        return True

    def settings(self) -> dict:
        from .sound import library

        from . import themes

        return {"values": load_config(), "defaults": json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")),
                "sounds": library(), "user_sounds": _user_sounds(), "themes": themes.themes()}

    def theme_css(self) -> str:
        """CSS custom properties of the chosen theme and corner style."""
        from . import themes

        return themes.css(themes.current()[1], themes.corners())

    def set_appearance(self, theme: str, corners: str) -> str:
        """Saves the theme and corner style at once (they apply instantly) and
        returns the new CSS; other unsaved settings on the form are untouched."""
        values = load_config()
        values["appearance"] = dict(values.get("appearance") or {}, theme=theme, corners=corners)
        save_overrides(diff(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")), values))
        return self.theme_css()

    def save_settings(self, values: dict) -> dict:
        defaults = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        overrides = diff(defaults, values)
        save_overrides(overrides)
        return overrides

    def reset_settings(self) -> bool:
        save_overrides({})
        return True

    def preview_sound(self, name: str, volume: float | None = None) -> bool:
        """Plays a sound at the volume on the form (saved or not), so the
        preview sounds like the alert in game."""
        from .sound import play_at, sound_path

        path = sound_path(name)
        if path is None:
            return False
        play_at(path, load_config()["sound"].get("volume", 0.5) if volume is None else volume)
        return True

    def add_sound(self, filename: str, samples_b64: str) -> dict:
        """A sound the page decoded (mono float32 at 44.1 kHz, base64), made an
        alert sound and saved to the user's sound folder."""
        import base64

        import numpy as np

        from .sound import library
        from .sound_import import RATE, prepare, safe_name, write

        try:
            x = prepare(np.frombuffer(base64.b64decode(samples_b64), "<f4"))
        except ValueError as e:
            return {"error": str(e)}
        name = safe_name(filename, set(library()))
        write(x, user_sounds_dir() / f"{name}.wav")
        return {"name": name, "seconds": round(len(x) / RATE, 2), "user_sounds": _user_sounds()}

    def remove_sound(self, name: str) -> dict:
        """Deletes one of the user's sounds. Severities that used it go back to
        their default sound."""
        path = user_sounds_dir() / f"{name}.wav"
        if path.parent != user_sounds_dir() or not path.exists():
            return {"error": "not one of your sounds"}
        path.unlink()
        user = user_config_path()
        overrides = json.loads(user.read_text(encoding="utf-8")) if user.exists() else {}
        sound = overrides.get("sound", {})
        for sev in [k for k, v in sound.items() if v == name]:
            del sound[sev]
        if "sound" in overrides and not sound:
            del overrides["sound"]
        save_overrides(overrides)
        return {"user_sounds": _user_sounds(), "sound": load_config()["sound"]}

    def storage(self) -> dict:
        """Size of the recorded matches, shown next to the retention settings."""
        sessions = [s for s in sessions_dir().iterdir() if s.is_dir()]
        size = sum(f.stat().st_size for s in sessions for f in s.rglob("*") if f.is_file())
        return {"matches": len(sessions), "mb": round(size / 1024 / 1024, 1)}

    def delete_matches(self, sessions: list[str]) -> int:
        """Deletes recorded matches (their whole folders); returns how many.
        Only folders directly inside sessions/ that hold a match log qualify."""
        import shutil

        root = sessions_dir().resolve()
        done = 0
        for name in sessions:
            folder = (root / name).resolve()
            if folder.parent == root and (folder / "log.jsonl").is_file():
                shutil.rmtree(folder, ignore_errors=True)
                done += not folder.exists()
        return done

    def set_setting(self, section: str, key: str, value) -> bool:
        """Saves one setting at once (used by switches that apply instantly)."""
        values = load_config()
        values[section] = dict(values.get(section) or {}, **{key: value})
        save_overrides(diff(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")), values))
        return True

    def update_status(self, force: bool = False) -> dict:
        """What the hub shows about updates: the latest release (from the daily
        check, or asked now with `force`) and whether this copy can install it."""
        from . import updates

        enabled = (load_config().get("updates") or {}).get("check", True)
        latest = updates.check(force=force) if (enabled or force) else None
        from .version import shown

        return {"current": shown(), "enabled": enabled, "newer": updates.newer(latest),
                "latest": latest.version if latest else None, "page": latest.page if latest else None,
                "can_install": updates.can_install() and bool(latest and latest.installer)}

    def update_now(self) -> dict:
        """Downloads and verifies the installer, schedules it, and asks the app
        (and this hub) to close; the installer reopens Reeve when it is done."""
        from . import updates
        from .launcher import QUIT_EVENT, signal

        latest = updates.check()
        if not updates.newer(latest) or not updates.can_install():
            return {"error": "no update to install"}
        try:
            installer = updates.download(latest)
        except Exception as e:
            return {"error": f"download failed: {e}"}
        updates.install(installer)
        signal(QUIT_EVENT)
        if self._window is not None:
            threading.Timer(0.5, self._window.destroy).start()
        return {"installing": latest.version}

    def open_url(self, url: str) -> bool:
        if url.startswith("https://github.com/"):
            os.startfile(url)
            return True
        return False

    def open_data_folder(self) -> bool:
        os.startfile(data_dir())
        return True


def main() -> None:
    import webview

    from .checks import use_app_identity

    use_app_identity()   # taskbar shows Reeve's icon instead of grouping under python.exe

    api = HubApi()
    api._window = webview.create_window("Reeve", HUB_HTML.as_uri(), js_api=api, width=1180, height=820,
                                       min_size=(900, 600), background_color="#0e1319")
    webview.start(icon=str(APP_ICON))


if __name__ == "__main__":
    main()
