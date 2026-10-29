# Roadmap

Each milestone ends with a visual validation by the user before work on the next one begins.

## Architecture direction (hub technology confirmed: pywebview)
- **Two parts, one Python codebase.** The in-game overlay stays a tiny tkinter window (it is the only part running during a match). A separate **hub** window, opened before or after matches, holds settings, match history, reports and the build editor.
- **Hub technology: pywebview** (native window rendered by the system WebView2, already present on Windows 11): modern HTML/CSS UI, reuses the report's charts, no bundled browser. Fallback: open the same UI in the default browser if WebView2 is missing. Alternatives considered: plain tkinter (dated for editors/tables), local web UI in the browser (no app window), Tauri (lightest binary, but adds Rust and a sidecar process), Qt/PySide6 (~100 MB of dependencies), Electron (150–300 MB RAM, against the lightweight goal).
- **User data in `%APPDATA%\reeve`** (config, sessions, custom sounds), separate from the program; a small SQLite index (stdlib) for history search, logs stay JSONL.
- **Tray icon** to start/stop the overlay and open the hub, so no terminal is needed.

## v0.1: MVP (build-independent tips)

| # | Deliverable | Validation | Status |
|---|-------------|------------|--------|
| M1 | Repository, scaffold, agents, game window detection, `snap` | `reeve window` reports the correct resolution | ✅ |
| M2 | Anchor and UI scale detection (multi-scale) | `inspect.html` shows the anchor box on screenshots | ✅ |
| M3 | Digit reading (resources, villagers per resource, population, clock, idle villagers) and production queue | Per-stage `inspect.html`, labeler, live `watch` and tests | ✅ |
| M4 | Live overlay: `--debug` view and clean alert mode | Boxes and values drawn over the game in a live match | ✅ |
| M5 | State layer (two-read confirmation, clock plausibility) and rules with three severities and alert sounds: idle villagers, idle town center, housed, floating resources; `replay` | Trigger each situation and confirm the alert; replay recorded sessions | ✅ |
| M6 | Post-match `report.html` (summary, villagers per resource, income per minute, stockpiles, population, alert timeline, audit frames); live income estimate | Check the timeline against the game's replay | ✅ |
| M7 | Age detection: current age (numeral I–IV above the clock), age-up progress and number of villagers building the landmark; age reached / started / builders in the report, age lines and age-up bands on the charts, age chip in the moment card | Play a match up to age III/IV with the overlay; check the detected times against the game's replay | ✅ |

## v0.2: App shell and distribution
Turns the command-line tool into an installable app.

| # | Deliverable | Status |
|---|-------------|--------|
| A1 | User data directory (`%APPDATA%\reeve`): config, sessions and custom sounds move out of the repository; migration of existing sessions | ✅ |
| A2 | Tray icon (pystray): overlay on/off, debug view, mute, open last report, open data folder, quit; windowless `reeve-app` entry point | ✅ |
| A3 | Hub v1 (pywebview, own process from the tray, double-click the icon): match history (newest first, ages, villagers at 10 min, time with each problem) opening each report; settings for alert thresholds, on/off per alert, sound per severity with preview, repeat on/off per severity, repeat interval, volume; saved as overrides and applied to the running overlay within seconds. Per-match `summary.json` instead of a SQLite index for now. Still to come here: alert card style, themes (A9) | ✅ |
| A4 | Session retention: keep everything 7 days, then only log + report up to 90 days, plus a total size cap; configurable in the hub; runs at startup | ✅ |
| A5 | Custom sounds from the hub: import any audio/video file into the sound library (the existing `import_sound.py` flow behind a UI) | ✅ |
| A6 | First-run checks: game in Borderless/Windowed mode, WebView2 present, first calibration | ✅ |
| A7 | Packaging: PyInstaller (one-folder build, fewer antivirus false positives than one-file) + Inno Setup installer; version shown in the hub and watermark | ✅ |
| A8 | Performance review against the targets (RAM currently ~60 MB vs. 50 MB target) with `perf-guardian` |  |
| A9 | Themes for the overlay and the report: the current Age-inspired gold theme (default), a neutral dark mode, and community palettes such as Dracula and Kitty; chosen in the hub |  |
| A10 | GitHub releases: each version is a tag `vX.Y.Z` with the installer attached and its notes in `docs/releases/`; `scripts/build.py --release` publishes it. Versions: `0.MINOR.PATCH`, patch releases for fixes and small additions | ✅ (v0.2.0) |
| A11 | Updates from the hub: at most one check a day against the latest GitHub release (stdlib HTTPS, no new dependency); a tray notice and a banner in the hub when a newer version exists, never during a match; "Update" downloads the installer and runs it silently (it closes and reopens Reeve). Needs public releases (see Public launch) |  |

## Public launch
The repository goes public once the project feels complete enough.

| # | Deliverable | Status |
|---|-------------|--------|
| P1 | License for the code (and a note on the bundled third-party assets: game icons, Pixabay sounds) |  |
| P2 | README for players first: what Reeve does, screenshots of the overlay, the report and the hub, install steps; development notes below |  |
| P3 | Support link (Buy Me a Coffee) in the README, the hub and `.github/FUNDING.yml` |  |
| P4 | Issue templates for bug reports (with `reeve doctor` output and `reeve.log`) and suggestions |  |

## Game data (prerequisite of v0.3)
Build orders need the whole game catalog, and the match history wants to know who played what.

| # | Deliverable | Status |
|---|-------------|--------|
| G1 | Civilization played in each match, shown in the match list and the report. Options to evaluate, cheapest first: read it from the screen (the civilization emblem is visible in the UI, matched like the age numeral); or link the player's AoE4World profile and fetch match metadata (civilization, opponent, map, result) from its public API after the match |  |
| G2 | Game catalog: civilizations, units, buildings and technologies with costs, times and icons, as versioned data files in the repository. Source to evaluate: AoE4World's open data (JSON plus icons) instead of scraping a wiki; check its license and keep the source and version recorded, as with the sounds |  |

## v0.3: Execution vs. build order
Timestamped diff of expected vs. actual villagers and resources, live (overlay alert when behind the build) and in the report.

## v0.4: Build orders in the hub
Import (aoe4guides or a native JSON format), create and edit build orders in the hub.

## v0.5: Smart build orders
Economy simulator: given the number of villagers per resource and the gather rates (civilization, technologies such as Wheelbarrow and Double Broadaxe), project the resources available at time T. The editor validates whether each build step is achievable. Uses the live income-per-villager estimate as a reality check.

## Later
- Income-based alerts (e.g. low income per villager on wood: drop-off too far).
- Sound themes and per-alert sound packs shared between users.
- Code signing (avoids SmartScreen warnings; auto-update is A11).
- Localization (affects text only; digits and icons are language-independent).
