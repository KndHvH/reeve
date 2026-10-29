# Reeve

Reeve (formerly aoe4-overlay / `aoe4ov`) is a macro assistant for AoE4: an overlay that reads the game UI through template matching. See `README.md`, `ROADMAP.md` and `docs/DECISIONS.md`.

## Project rules
- **Computational cost is a requirement**: no heavy dependencies (torch, OCR, Qt, Electron), no full-screen capture inside the loop, a default loop of one read every 2 s (configurable), and the overlay is redrawn only when state changes. When in doubt, consult the `perf-guardian` agent.
- **Nothing hardcoded per resolution**: ROIs live in `assets/layout.json` in reference coordinates relative to an anchor and are scaled at runtime.
- **Everything inspectable**: every new pipeline stage needs a visual output (`inspect.html`, `--debug`) for the user to validate.
- **Milestone checkpoints**: deliver a ROADMAP milestone, ask the user to validate it, and only then move on.
- Record non-obvious decisions in `docs/DECISIONS.md`.
- Use only ctypes for Win32 (no pywin32). Exception: the tray icon uses `pystray` (pure Python over ctypes).
- **Language**: all code, comments, docs, CLI/UI text, log keys and commit messages are in English. Conversation with the user may be in Portuguese.

## Commands
- `uv sync`, `uv run pytest`, `uv run reeve <cmd>`
- `uv run python scripts/build.py`: PyInstaller one-folder app (`packaging/reeve.spec`) plus the Inno Setup installer (`packaging/reeve.iss`)
