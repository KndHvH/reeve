"""Rotulador: você confirma ou corrige o que o leitor leu.

Cada imagem confirmada vira fixture de teste (tests/fixtures/<nome>.png + .json)
e o banco de glifos é refeito. É assim que os seus rótulos viram a "verdade"
que os testes garantem e a referência que o leitor usa.
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
from .reader import _clock_y_hint, read_frame

BG, CARD, FG, MUTED = "#0f1115", "#171a21", "#e6e6e6", "#9aa4b2"
GOOD, WARN, BAD = "#3ddc84", "#f5c542", "#ff5c5c"
FIELDS = ["clock", "pop", "idle", "food", "vil_food", "wood", "vil_wood", "gold", "vil_gold", "stone", "vil_stone"]
NAMES = {
    "clock": "Relógio", "pop": "População", "idle": "Ociosos",
    "food": "Comida", "wood": "Madeira", "gold": "Ouro", "stone": "Pedra",
    "vil_food": "Aldeões comida", "vil_wood": "Aldeões madeira", "vil_gold": "Aldeões ouro", "vil_stone": "Aldeões pedra",
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
        self.root.title("aoe4ov · rotulador")
        self.root.configure(bg=BG)
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(padx=16, pady=16)
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
        self.img = img
        self.photos = []

        head = tk.Label(self.body, text=f"{png.name}   ({self.i + 1}/{len(self.paths)})",
                        bg=BG, fg=FG, font=("Segoe UI Variable", 12, "bold"))
        head.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        if not self.frame.match.ok:
            tk.Label(self.body, text="Âncora não encontrada: essa imagem não parece o jogo.", bg=BG, fg=BAD,
                     font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=4, sticky="w")

        self.entries: dict[str, tk.Entry] = {}
        for row, name in enumerate(FIELDS, start=2):
            x, y, w, h = self.frame.rois[name]
            r = self.frame.readings[name]
            color = GOOD if r.conf >= 0.85 else WARN if r.conf >= MIN_SCORE else BAD
            ph = _photo(img.crop((x, y, x + w, y + h)), 4 if name != "clock" else 3)
            self.photos.append(ph)
            tk.Label(self.body, text=NAMES[name], bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w", width=16).grid(row=row, column=0, sticky="w")
            tk.Label(self.body, image=ph, bg="#000").grid(row=row, column=1, sticky="w", padx=8, pady=2)
            e = tk.Entry(self.body, width=10, font=("Consolas", 13), bg=CARD, fg=FG, insertbackground=FG,
                         relief="flat", highlightthickness=2, highlightbackground=color, highlightcolor=color)
            e.insert(0, format_text(name, r.text))
            e.grid(row=row, column=2, padx=8)
            tk.Label(self.body, text=f"{r.conf:.2f}", bg=BG, fg=color, font=("Consolas", 10)).grid(row=row, column=3)
            self.entries[name] = e

        row = len(FIELDS) + 2
        self.producing = tk.BooleanVar(value=self.frame.values["producing_villager"])
        tk.Checkbutton(self.body, text=f"Aldeão em produção (score {self.frame.production.score:.2f})",
                       variable=self.producing, bg=BG, fg=FG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, font=("Segoe UI", 10)).grid(row=row, column=0, columnspan=4, sticky="w", pady=8)
        px, py, pw, ph_ = self.frame.production.region
        prod = _photo(img.crop((px, py, px + pw, py + ph_)), 2)
        self.photos.append(prod)
        tk.Label(self.body, image=prod, bg="#000").grid(row=row + 1, column=0, columnspan=4, sticky="w")

        bar = tk.Frame(self.body, bg=BG)
        bar.grid(row=row + 2, column=0, columnspan=4, sticky="e", pady=(12, 0))
        for text, cmd, color in (("Pular", self.skip, CARD), ("Salvar  ⏎", self.save, "#2a6df4")):
            tk.Button(bar, text=text, command=cmd, bg=color, fg=FG, relief="flat", padx=14, pady=6,
                      activebackground=color, activeforeground=FG, font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        self.root.bind("<Return>", lambda _: self.save())
        self.root.bind("<Escape>", lambda _: self.skip())

    def save(self):
        label = {name: self.entries[name].get().strip() for name in FIELDS}
        label["producing_villager"] = bool(self.producing.get())
        label["source"] = self.paths[self.i].stem
        name = _fixture_name(self.paths[self.i], label, self.img.height)
        shutil.copy(self.paths[self.i], FIXTURES / f"{name}.png")
        (FIXTURES / f"{name}.json").write_text(json.dumps(label, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"salvo: tests/fixtures/{name}.png")
        self.saved += 1
        self.i += 1
        self.show()

    def skip(self):
        self.i += 1
        self.show()

    def finish(self):
        if self.saved:
            counts = build()
            print(f"banco de glifos refeito: {counts}")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run(paths: list[Path]) -> None:
    Labeler(paths).run()
