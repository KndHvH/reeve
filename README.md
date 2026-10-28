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

## Requirements
- Windows 10/11, with AoE4 running in **Borderless** or **Windowed** mode. Overlays are not visible in exclusive fullscreen.
- [uv](https://docs.astral.sh/uv/)

## Usage
```powershell
uv sync                                 # install dependencies
uv run aoe4ov window                    # show the detected game window and its resolution
uv run aoe4ov snap --count 6 --every 20 # save in-game screenshots to captures/
uv run aoe4ov inspect captures/*.png    # write .inspect.html files showing every reading stage, field by field
uv run aoe4ov label captures/*.png      # labeler: confirm or correct readings to create test fixtures and glyphs
uv run aoe4ov glyphs                    # rebuild the glyph bank from the labeled fixtures
uv run aoe4ov watch                     # live readings in the terminal; records sessions/<start>/log.jsonl and fail_*.png
uv run aoe4ov overlay                   # overlay on top of the game: alert cards and sounds (--mute for silence)
uv run aoe4ov overlay --debug           # debug overlay: detection, values, confidence, timings, RAM/CPU, alerts
uv run aoe4ov replay sessions/<start>/log.jsonl  # replay a recorded session through the alert rules
uv run aoe4ov sounds                    # list the alert sound library (--play NAME to preview)
uv run aoe4ov report sessions/<start>   # write the post-match report.html (also written automatically when a match ends)
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

Each severity plays a sound from the library in `assets/sounds/library/`, chosen by name in `config/rules.json` ("sound"); defaults: info `blip`, warn `chime`, critical `alarm_low`. A sound plays when an alert appears or escalates; warn and critical repeat every 5 s while unresolved, info plays once. `aoe4ov sounds` lists the library, `aoe4ov sounds --play NAME` previews a sound and `overlay --mute` silences everything. New sounds are imported with `scripts/import_sound.py <file> <name>` (any format ffmpeg reads; trimmed, capped at 1.5 s and loudness-normalized; source and license recorded in `assets/sounds/library/SOURCE.md`).

Slow-changing values are confirmed over two consecutive readings, so a single misread never triggers an alert. Use `aoe4ov replay` to see which alerts a recorded session would produce, and why, after editing the thresholds.

## Post-match report
When a match ends (the match has not been read for 10 s: end screen, menu or alt-tab), `sessions/<start>/report.html` is written: a single offline HTML file with a summary (villagers at 5/10/15 min, when each age was reached, when its landmark started and how many villagers built it, time with the town center idle, time housed, idle villagers, floating resources, average income) and charts over game time for villagers per resource, income per minute, stockpiles, population and the alert timeline. Hovering a chart moves a shared cursor; clicking pins a moment and shows the values read then, next to the panel as it was captured (a small crop is kept every 10 s of game time).

Income is estimated from the stockpile: the sum of its increases over the last 60 s of game time, per minute, after a median-of-3 filter against single misreads. Spending is ignored, so a drop-off that lands in the same reading as a purchase is partly hidden and the estimate leans slightly low. Income per villager divides by the villagers on that resource. It is computed live (shown in `overlay --debug`) and logged with every reading.

