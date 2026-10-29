# Development

Reeve reads the game's UI from small screen regions: the resource panel is located by template matching on the resource icon column (resolution from Windows, UI scale from the match), digits are read by template matching against a glyph bank (no OCR), and the readings feed a state tracker, the alert rules and the match recorder. Design choices and their reasons are in [DECISIONS.md](DECISIONS.md); planned work in [ROADMAP.md](../ROADMAP.md).

Targets: a single process under 50 MB of RAM and 5 ms per cycle, one read every 2 s, capturing only small regions.

## Setup
Requires [uv](https://docs.astral.sh/uv/) and Windows.

```powershell
uv sync                                 # install dependencies
uv run pytest                           # run the test suite
uv run reeve                            # the app: overlay + tray icon
```

## Commands

```powershell
uv run reeve hub                        # the hub on its own: match history, reports, settings
uv run reeve doctor [--wait 5]          # check WebView2, the game window, display mode and the resource panel
uv run reeve clean [--dry-run]          # apply session retention now (the app runs it at startup)
uv run reeve window                     # show the detected game window and its resolution
uv run reeve snap --count 6 --every 20  # save in-game screenshots to captures/
uv run reeve inspect captures/*.png     # write .inspect.html files showing every reading stage, field by field
uv run reeve label [images|folders]     # labeler: confirm or correct readings (default: low-confidence reads of all matches)
uv run reeve glyphs                     # rebuild the glyph bank from the labeled fixtures
uv run reeve watch                      # live readings in the terminal; records a session
uv run reeve overlay [--debug] [--mute] # overlay without the tray; --debug shows detection, values, confidence, timings, RAM/CPU
uv run reeve replay <session>/log.jsonl # replay a recorded session through the alert rules
uv run reeve sounds [--play NAME]       # list or preview the alert sound library
uv run reeve report [session]           # rewrite a report (default: latest match)
uv run reeve migrate                    # move sessions recorded in ./sessions into the data folder
```

## Build and release
Building the installer also needs [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
uv run python scripts/build.py              # dist/Reeve/Reeve.exe (PyInstaller, one folder) and dist/Reeve-<version>-setup.exe
uv run python scripts/build.py --release    # also publish GitHub release v<version>, notes from docs/releases/v<version>.md
```

The version comes from `src/reeve/__init__.py`. `Reeve.exe` runs the tray app, `Reeve.exe hub` the hub; a second start while Reeve runs opens the hub. The packaged app has no console: output and errors go to `reeve.log` in the data folder.

## Configuration and data
- `config/rules.json` holds the shipped defaults of every setting. The user's `%APPDATA%\reeve\config\rules.json` holds only what they changed and is merged on top. `REEVE_HOME` points the whole data folder elsewhere (the tests always do).
- `%APPDATA%\reeve\sessions\<start>\` holds each match: `log.jsonl` (one line per reading), `summary.json`, `report.html`, audit frames every 10 s of game time and the crops of doubtful readings.
- `assets/layout.json` holds the regions of interest in reference coordinates (720p, UI 100%) relative to the anchor; nothing is tied to a resolution.

## Alerts and sounds
Slow-changing values are confirmed over two consecutive readings, so a single misread never triggers an alert. `reeve replay` shows which alerts a recorded session produces after the thresholds change.

The built-in sounds live in `assets/sounds/library/`; `scripts/import_sound.py <file> <name>` adds one (needs ffmpeg; trimmed, capped at 1.5 s and leveled like the sounds added in the hub, source and license recorded in `SOURCE.md`). The volume follows a squared curve: 0 is silent, 0.5 the default level, 1 is 12 dB louder.

## Income estimate
Income is the sum of the stockpile's increases over the last 60 s of game time, per minute, after a median-of-3 filter against single misreads. Spending is ignored, so a drop-off read together with a purchase is partly hidden and the estimate leans slightly low. Income per villager divides by the villagers on that resource.

## README screenshots
`docs/screenshots/` holds the hub and report captures used in the README, taken from real matches with the default settings (a copy of the sessions in a temporary `REEVE_HOME`, so the user's settings do not show). Retake them when the UI changes noticeably.
