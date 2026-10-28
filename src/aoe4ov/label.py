"""Labeler: you confirm or correct what the reader read.

Each confirmed image becomes a test fixture (tests/fixtures/<name>.png + .json)
and the glyph bank is rebuilt. This is how your labels become the "ground
truth" the tests enforce and the reference the reader uses.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image

from .digits import MIN_SCORE
from .glyphs import FIXTURES, build
from .reader import _clock_y_hint, parse, read_frame

BG, CARD, FG, MUTED = "#0f1115", "#171a21", "#e6e6e6", "#9aa4b2"
GOOD, WARN, BAD = "#3ddc84", "#f5c542", "#ff5c5c"
CROP_H = 40   # height (px) of each crop in the window, whatever the resolution
PROD_H = 300  # height (px) of the production queue crop
FIELDS = ["clock", "pop", "idle", "food", "vil_food", "wood", "vil_wood", "gold", "vil_gold", "stone", "vil_stone"]
NAMES = {
    "clock": "Clock", "pop": "Population", "idle": "Idle",
    "food": "Food", "wood": "Wood", "gold": "Gold", "stone": "Stone",
    "vil_food": "Villagers on food", "vil_wood": "Villagers on wood", "vil_gold": "Villagers on gold", "vil_stone": "Villagers on stone",
}


def format_text(name: str, text: str) -> str:
    if name == "clock" and text.isdigit() and len(text) >= 4:
        h, mm, ss = text[:-4], text[-4:-2], text[-2:]
        return f"{h}:{mm}:{ss}" if h else f"{mm}:{ss}"
    return text


def _photo(im: Image.Image, zoom: int) -> tk.PhotoImage:
    im = im.resize((im.width * zoom, im.height * zoom), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))


def validate(label: dict) -> list[str]:
    """Empty or malformed fields cannot become a test."""
    errors = []
    for name in FIELDS:
        text = label[name].replace(":", "") if name == "clock" else label[name]
        if not text or parse(name, text) is None:
            errors.append(NAMES[name])
    return errors


def _fixture_name(png: Path, label: dict, height: int) -> str:
    base = f"{height}p_{label['clock'].replace(':', '')}"
    if int(label["idle"] or 0) > 0:
        base += f"_idle{label['idle']}"
    name, n = base, 2
    while (FIXTURES / f"{name}.png").exists():
        name, n = f"{base}_{n}", n + 1
    return name


class Labeler:
    def __init__(self, paths: list[Path]):
        self.paths = paths
        self.i = 0
        self.saved = 0
        self.root = tk.Tk()
        self.root.title("aoe4ov · labeler")
        self.root.configure(bg=BG)
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(padx=16, pady=16)
        self.root.protocol("WM_DELETE_WINDOW", self.finish)
        self.show()

    def show(self):
        for w in self.body.winfo_children():
            w.destroy()
        if self.i >= len(self.paths):
            self.finish()
            return
        png = self.paths[self.i]
        img = Image.open(png).convert("RGB")
        _clock_y_hint.clear()
        self.frame = read_frame(np.asarray(img))
        if not self.frame.match.ok:
            # E.g. a capture with another window on top (the browser). Nothing to label.
            print(f"skipped (panel not found): {png.name}")
            self.i += 1
            self.show()
            return
        self.img = img
        self.photos = []

        head = tk.Label(self.body, text=f"{png.name}   ({self.i + 1}/{len(self.paths)})",
                        bg=BG, fg=FG, font=("Segoe UI Variable", 12, "bold"))
        head.grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        self.error = tk.Label(self.body, text="", bg=BG, fg=BAD, font=("Segoe UI", 10))
        self.error.grid(row=1, column=0, columnspan=5, sticky="w")

        self.entries: dict[str, tk.Entry] = {}
        for row, name in enumerate(FIELDS, start=2):
            x, y, w, h = self.frame.rois[name]
            r = self.frame.readings[name]
            color = GOOD if r.conf >= 0.85 else WARN if r.conf >= MIN_SCORE else BAD
            if name == "clock" and r.glyphs:
                # The clock region is tall (the clock moves down on age-up): show only the band that was read.
                gy0 = min(g.y for g in r.glyphs)
                gy1 = max(g.y + g.h for g in r.glyphs)
                pad = max(3, (gy1 - gy0) // 2)
                y, h = y + max(0, gy0 - pad), gy1 - gy0 + 2 * pad
            crop = img.crop((x, y, x + w, y + h))
            ph = _photo(crop, max(1, round(CROP_H / max(1, crop.height))))
            self.photos.append(ph)
            tk.Label(self.body, text=NAMES[name], bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w", width=16).grid(row=row, column=0, sticky="w")
            tk.Label(self.body, image=ph, bg="#000").grid(row=row, column=1, sticky="w", padx=8, pady=2)
            e = tk.Entry(self.body, width=10, font=("Consolas", 13), bg=CARD, fg=FG, insertbackground=FG,
                         relief="flat", highlightthickness=2, highlightbackground=color, highlightcolor=color)
            e.insert(0, format_text(name, r.text))
            e.grid(row=row, column=2, padx=8)
            tk.Label(self.body, text=f"{r.conf:.2f}", bg=BG, fg=color, font=("Consolas", 10)).grid(row=row, column=3)
            self.entries[name] = e

        # Right column: production queue + the checkbox, always visible.
        side = tk.Frame(self.body, bg=BG)
        side.grid(row=2, column=4, rowspan=len(FIELDS), sticky="n", padx=(24, 0))
        tk.Label(side, text="Production queue", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w")
        px, py, pw, ph_ = self.frame.production.region
        prod_img = img.crop((px, py, px + pw, py + ph_))
        prod = _photo(prod_img, max(1, round(PROD_H / max(1, prod_img.height))))
        self.photos.append(prod)
        tk.Label(side, image=prod, bg="#000").pack(anchor="w", pady=4)
        self.producing = tk.BooleanVar(value=self.frame.values["producing_villager"])
        tk.Checkbutton(side, text=f"Villager in production (score {self.frame.production.score:.2f})",
                       variable=self.producing, bg=BG, fg=FG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, font=("Segoe UI", 10)).pack(anchor="w")

        row = len(FIELDS) + 2
        bar = tk.Frame(self.body, bg=BG)
        bar.grid(row=row, column=0, columnspan=5, sticky="e", pady=(12, 0))
        for text, cmd, color in (("Skip", self.skip, CARD), ("Save  ⏎", self.save, "#2a6df4")):
            tk.Button(bar, text=text, command=cmd, bg=color, fg=FG, relief="flat", padx=14, pady=6,
                      activebackground=color, activeforeground=FG, font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        self.root.bind("<Return>", lambda _: self.save())
        self.root.bind("<Escape>", lambda _: self.skip())

    def save(self):
        label = {name: self.entries[name].get().strip() for name in FIELDS}
        errors = validate(label)
        if errors:
            self.error.config(text="Fix before saving: " + ", ".join(errors))
            return
        label["producing_villager"] = bool(self.producing.get())
        label["source"] = self.paths[self.i].stem
        name = _fixture_name(self.paths[self.i], label, self.img.height)
        shutil.copy(self.paths[self.i], FIXTURES / f"{name}.png")
        (FIXTURES / f"{name}.json").write_text(json.dumps(label, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"saved: tests/fixtures/{name}.png")
        self.saved += 1
        self.i += 1
        self.show()

    def skip(self):
        self.i += 1
        self.show()

    def finish(self):
        if self.saved:
            counts = build()
            print(f"glyph bank rebuilt: {counts}")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run(paths: list[Path]) -> None:
    Labeler(paths).run()
