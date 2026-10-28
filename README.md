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
uv run aoe4ov overlay                   # overlay on top of the game: alert cards only
uv run aoe4ov overlay --debug           # debug overlay: detection, values, confidence, timings, RAM/CPU, alerts
uv run aoe4ov replay sessions/<start>/log.jsonl  # replay a recorded session through the alert rules
uv run pytest                           # run the test suite
```

## Alerts
Rules and thresholds are in `config/rules.json` (idle villagers, town center idle, housed, floating resources by game phase). Slow-changing values are confirmed over two consecutive readings, so a single misread never triggers an alert. Use `aoe4ov replay` to see which alerts a recorded session would produce, and why, after editing the thresholds.
