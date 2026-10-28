# Roadmap

## v0.1: MVP (build-independent tips)
Each milestone ends with a visual validation by the user before work on the next one begins.

| # | Deliverable | Validation | Status |
|---|-------------|------------|--------|
| M1 | Repository, scaffold, agents, game window detection, `snap` | `aoe4ov window` reports the correct resolution | ✅ |
| M2 | Anchor and UI scale detection (multi-scale) | `inspect.html` shows the anchor box on screenshots | ✅ |
| M3 | Digit reading (resources, villagers per resource, population, clock, idle villagers) and production queue | Per-stage `inspect.html`, labeler, live `watch` and tests | ✅ |
| M4 | Live overlay: `--debug` view and clean alert mode | Boxes and values drawn over the game in a live match | ✅ |
| M5 | State layer (two-read confirmation, clock plausibility) and rules with three severities and alert sounds: idle villagers, idle town center, housed, floating resources; `replay` | Trigger each situation and confirm the alert; replay recorded sessions | ✅ |
| M6 | Post-match `report.html` (summary, villagers per resource, income per minute, stockpiles, population, alert timeline, audit frames); live income estimate | Check the timeline against the game's replay | 🔎 awaiting validation |

## v0.2: Execution vs. build order
Timestamped diff of expected vs. actual villagers and resources.

## v0.3: Build orders
Import (aoe4guides or a native JSON format), create and edit.

## v0.4: Smart build orders
Economy simulator: given the number of villagers per resource and the gather rates (civilization, technologies such as Wheelbarrow and Double Broadaxe), project the resources available at time T. The editor validates whether each build step is achievable.

## Later
- Localization (affects text only; digits and icons are language-independent).
