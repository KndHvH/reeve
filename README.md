# aoe4-overlay

A lightweight overlay for **Age of Empires IV**. AoE4 exposes no live game-state API, so the overlay **reads the game's own UI** from small screen regions using digit template matching (no OCR) and provides macro tips:

- idle villagers
- town center not producing villagers
- housed (population at the cap)
- floating resources

When the match ends, it produces a **per-second report**: villagers on each resource, resource stockpiles and population.

## Principles
- **Low cost**: a single process, targeting < 50 MB of RAM and < 5 ms per cycle, with one read every 2 s by default (configurable). Only small screen regions are captured.
- **Zero configuration**: the resolution comes from Windows, and the UI scale is detected from an anchor (the resource icon column).
- **No black boxes**: every stage has a visual inspection tool (see `docs/DECISIONS.md` and `ROADMAP.md`).

## Your data
Settings, recorded matches and your own sounds live in `%APPDATA%\aoe4ov`: `config\rules.json` holds only the settings you changed, on top of the shipped defaults in `config/rules.json`; `sessions\` holds each match's log, audit frames and report; `sounds\` holds your own alert sounds. Set `AOE4OV_HOME` to use another folder.

Old matches are trimmed when the app starts: everything is kept for 7 days, then only the log, report and summary (the audit images go) up to 90 days, and older matches are deleted; above 500 MB in total the oldest are trimmed first. All three limits are in the hub's settings; `aoe4ov clean --dry-run` shows what would be removed.

## Requirements
- Windows 10/11, with AoE4 running in **Borderless** or **Windowed** mode. Overlays are not visible in exclusive fullscreen.
- [uv](https://docs.astral.sh/uv/)

## Usage
Run `uv run aoe4ov` (or the windowless `aoe4ov-app`): the overlay starts with a tray icon whose menu turns the overlay on/off, switches to the debug view, mutes the sounds, opens the hub (double-click the icon), the last report or the data folder, and quits. The hub lists every recorded match with its report and holds the settings (alert thresholds, sounds, repetition, volume); saved settings apply to the running overlay within a few seconds.

```powershell
uv sync                                 # install dependencies
uv run aoe4ov                           # the app: overlay + tray icon
uv run aoe4ov hub                       # the hub on its own: match history, reports, settings
uv run aoe4ov clean [--dry-run]         # apply session retention now (the app runs it at startup)
uv run aoe4ov window                    # show the detected game window and its resolution
uv run aoe4ov snap --count 6 --every 20 # save in-game screenshots to captures/
uv run aoe4ov inspect captures/*.png    # write .inspect.html files showing every reading stage, field by field
uv run aoe4ov label [images|folders]    # labeler: confirm or correct readings (default: low-confidence reads of all matches)
uv run aoe4ov glyphs                    # rebuild the glyph bank from the labeled fixtures
uv run aoe4ov watch                     # live readings in the terminal; records sessions/<start>/log.jsonl and fail_*.png
uv run aoe4ov overlay                   # overlay on top of the game: alert cards and sounds (--mute for silence)
uv run aoe4ov overlay --debug           # debug overlay: detection, values, confidence, timings, RAM/CPU, alerts
uv run aoe4ov replay sessions/<start>/log.jsonl  # replay a recorded session through the alert rules
uv run aoe4ov sounds                    # list the alert sound library (--play NAME to preview)
uv run aoe4ov report [session]          # rewrite a report (default: latest match; written automatically when a match ends)
uv run aoe4ov migrate                   # move sessions recorded in ./sessions into the data folder
uv run pytest                           # run the test suite
```

## Alerts
Rules and thresholds are in `config/rules.json`. Each alert has a severity: **info** (blue, silent), **warn** (yellow) and **critical** (red).

| Alert | warn | critical |
|---|---|---|
| Idle villagers | 1–2 idle | 3 or more |
| Town center idle | after 6 s | after 10 s |
| Population / houses | ≥ 80% of the cap | ≥ 90% of the cap |
| Floating resources | above the next phase's limit | two phases ahead (info: above the current phase's limit) |

Each severity plays a sound from the library in `assets/sounds/library/`, chosen by name in `config/rules.json` ("sound"); defaults: info `blip`, warn `chime`, critical `alarm_low`. A sound plays when an alert appears or escalates; warn and critical repeat every 5 s while unresolved, info plays once. `aoe4ov sounds` lists the library, `aoe4ov sounds --play NAME` previews a sound and `overlay --mute` silences everything. The volume (hub settings) goes from silent at 0% to loud at 100%; the default 50% is a comfortable level. Your own sounds are added in the hub (Settings, Sounds, "Add sound"): any audio or video file the browser engine can decode (mp3, ogg, wav, flac, the audio of mp4/webm), trimmed, capped at 1.5 s and leveled like the built-in ones, and saved to the `sounds` folder of your data. Built-in sounds are added with `scripts/import_sound.py <file> <name>` (needs ffmpeg; source and license recorded in `assets/sounds/library/SOURCE.md`).

Slow-changing values are confirmed over two consecutive readings, so a single misread never triggers an alert. Use `aoe4ov replay` to see which alerts a recorded session would produce, and why, after editing the thresholds.

## Post-match report
When a match ends (the match has not been read for 10 s: end screen, menu or alt-tab), `sessions/<start>/report.html` is written: a single offline HTML file with a summary (villagers at 5/10/15 min, when each age was reached, when its landmark started and how many villagers built it, time with the town center idle, time housed, idle villagers, floating resources, average income) and charts over game time for villagers per resource, income per minute, stockpiles, population and the alert timeline. Hovering a chart moves a shared cursor; clicking pins a moment and shows the values read then, next to the panel as it was captured (a small crop is kept every 10 s of game time).

Income is estimated from the stockpile: the sum of its increases over the last 60 s of game time, per minute, after a median-of-3 filter against single misreads. Spending is ignored, so a drop-off that lands in the same reading as a purchase is partly hidden and the estimate leans slightly low. Income per villager divides by the villagers on that resource. It is computed live (shown in `overlay --debug`) and logged with every reading.

