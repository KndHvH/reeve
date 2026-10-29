# Report icons

`pop`, `food`, `wood`, `gold`, `stone` and `villager` are cropped from Age of Empires IV's own UI (resource panel) in captures stored under `tests/fixtures/`, with the panel background made transparent. They are game assets of Microsoft / Relic Entertainment, used under Microsoft's Game Content Usage Rules (non-commercial fan projects). Replace them before any commercial distribution.

`builder` is aoe4guides.com's builder icon (`/assets/resources/repair.webp`, from the MIT-licensed [aoe4-guides](https://github.com/jensbuehl/aoe4-guides) repository), converted to PNG; a game asset under the same rules. The icons in a build's notes are downloaded from aoe4guides.com when the build is imported and stored in the user's data folder, never shipped with Reeve.
`rally` is aoe4guides.com's rally point picture (`/assets/pictures/resource/rally.webp`), from the same repository, converted to PNG.

# Flags and civilizations

`assets/flags/<abbr>.png` are aoe4guides.com's civilization flags (`public/assets/flags/<code>-large.webp` in the same repository), resized and converted to PNG. `assets/catalog/civilizations.json` (names, villager training time) comes from [AoE4World's open data](https://github.com/aoe4world/data), which its authors publish for use in projects under the same Game Content Usage Rules; its source and version are recorded in the file. Both are written by `scripts/catalog.py`. A civilization's units, buildings, technologies and their icons are AoE4World's too, downloaded to the user's data folder for the civilization of the build in use, never shipped with Reeve.
