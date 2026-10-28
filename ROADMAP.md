# Roadmap

Each milestone ends with a visual validation by the user before work on the next one begins.

## Architecture direction (proposed, to be confirmed in v0.2)
- **Two parts, one Python codebase.** The in-game overlay stays a tiny tkinter window (it is the only part running during a match). A separate **hub** window, opened before or after matches, holds settings, match history, reports and the build editor.
- **Hub technology: pywebview** (native window rendered by the system WebView2, already present on Windows 11): modern HTML/CSS UI, reuses the report's charts, no bundled browser. Fallback: open the same UI in the default browser if WebView2 is missing. Alternatives considered: plain tkinter (dated for editors/tables), local web UI in the browser (no app window), Tauri (lightest binary, but adds Rust and a sidecar process), Qt/PySide6 (~100 MB of dependencies), Electron (150–300 MB RAM, against the lightweight goal).
- **User data in `%APPDATA%\aoe4ov`** (config, sessions, custom sounds), separate from the program; a small SQLite index (stdlib) for history search, logs stay JSONL.
- **Tray icon** to start/stop the overlay and open the hub, so no terminal is needed.

## v0.1: MVP (build-independent tips)

| # | Deliverable | Validation | Status |
|---|-------------|------------|--------|
| M1 | Repository, scaffold, agents, game window detection, `snap` | `aoe4ov window` reports the correct resolution | ✅ |
| M2 | Anchor and UI scale detection (multi-scale) | `inspect.html` shows the anchor box on screenshots | ✅ |
| M3 | Digit reading (resources, villagers per resource, population, clock, idle villagers) and production queue | Per-stage `inspect.html`, labeler, live `watch` and tests | ✅ |
| M4 | Live overlay: `--debug` view and clean alert mode | Boxes and values drawn over the game in a live match | ✅ |
| M5 | State layer (two-read confirmation, clock plausibility) and rules with three severities and alert sounds: idle villagers, idle town center, housed, floating resources; `replay` | Trigger each situation and confirm the alert; replay recorded sessions | ✅ |
| M6 | Post-match `report.html` (summary, villagers per resource, income per minute, stockpiles, population, alert timeline, audit frames); live income estimate | Check the timeline against the game's replay | ✅ |
| M7 | Age detection: current age (numeral I–IV above the clock), age-up in progress with its progress bar; age-up start/finish times in the report and age bands on the charts (prerequisite for build-order comparison) | Play a match up to age III/IV with the overlay; check the detected times against the game's replay | 🧪 collecting data: top-center frames are now saved every 10 s |

## v0.2: App shell and distribution
Turns the command-line tool into an installable app.

| # | Deliverable |
|---|-------------|
| A1 | User data directory (`%APPDATA%\aoe4ov`): config, sessions and custom sounds move out of the repository; migration of existing sessions |
| A2 | Tray icon (ctypes, no new dependency): start/stop overlay, debug toggle, mute, open hub, quit |
| A3 | Hub v1 (pywebview): match history with search (SQLite index) and the reports; settings for alert thresholds, severities, sound per alert with preview, volume |
| A4 | Session retention: keep everything 7 days, then only log + report up to 90 days, plus a total size cap; configurable in the hub; runs at startup |
| A5 | Custom sounds from the hub: import any audio/video file into the sound library (the existing `import_sound.py` flow behind a UI) |
| A6 | First-run checks: game in Borderless/Windowed mode, WebView2 present, first calibration |
| A7 | Packaging: PyInstaller (one-folder build, fewer antivirus false positives than one-file) + Inno Setup installer; version shown in the hub and watermark |
| A8 | Performance review against the targets (RAM currently ~60 MB vs. 50 MB target) with `perf-guardian` |

## v0.3: Execution vs. build order
Timestamped diff of expected vs. actual villagers and resources, live (overlay alert when behind the build) and in the report.

## v0.4: Build orders in the hub
Import (aoe4guides or a native JSON format), create and edit build orders in the hub.

## v0.5: Smart build orders
Economy simulator: given the number of villagers per resource and the gather rates (civilization, technologies such as Wheelbarrow and Double Broadaxe), project the resources available at time T. The editor validates whether each build step is achievable. Uses the live income-per-villager estimate as a reality check.

## Later
- Income-based alerts (e.g. low income per villager on wood: drop-off too far).
- Sound themes and per-alert sound packs shared between users.
- Code signing (avoids SmartScreen warnings) and auto-update.
- Localization (affects text only; digits and icons are language-independent).
