"""Overlay transparente por cima do jogo (por enquanto só o modo debug).

Mostra o que o leitor está vendo: âncora, regiões com valor e confiança, fila
de produção e um HUD com janela, escala, tempos, RAM e CPU.

- A janela é excluída das capturas de tela (WDA_EXCLUDEFROMCAPTURE), senão o
  próprio overlay apareceria na imagem lida. Como garantia extra, nada é
  desenhado dentro das regiões lidas.
- Cliques atravessam (WS_EX_TRANSPARENT) e a janela nunca pega o foco, então
  o jogo continua em primeiro plano.
- O canvas só é redesenhado a cada leitura (padrão 2 s), sem animação.
"""

from __future__ import annotations

import ctypes
import tkinter as tk

from .digits import MIN_SCORE
from .live import LiveReader, Step
from .metrics import CpuMeter, ram_mb

KEY = "#010203"  # cor tratada como transparente
BG, CARD, FG, MUTED = "#0f1115", "#14171d", "#e6e6e6", "#8b93a1"
GOOD, WARN, BAD, ACCENT = "#3ddc84", "#f5c542", "#ff5c5c", "#4da3ff"
FONT = "Segoe UI"

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
WDA_EXCLUDEFROMCAPTURE = 0x11

user32 = ctypes.windll.user32


def _conf_color(c: float) -> str:
    return GOOD if c >= 0.85 else WARN if c >= MIN_SCORE else BAD


class DebugOverlay:
    def __init__(self, every: float):
        self.every = every
        self.live = LiveReader(every)
        self.cpu = CpuMeter()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", KEY)
        self.root.configure(bg=KEY)
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.excluded = self._win32_setup()
        self.geom = None
        self.last_events: list[str] = []
        self.root.after(100, self.tick)

    def _win32_setup(self) -> bool:
        hwnd = user32.GetParent(self.root.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))

    # --- loop -------------------------------------------------------------
    def tick(self):
        s = self.live.step()
        if s.events:
            self.last_events = (self.last_events + s.events)[-3:]
        if s.win is None or s.status == "sem_jogo":
            self.root.withdraw()
        else:
            g = (s.win.width, s.win.height, s.win.left, s.win.top)
            if g != self.geom:
                self.root.geometry("{}x{}+{}+{}".format(*g))
                self.geom = g
            self.root.deiconify()
            self.draw(s)
        self.root.after(int(self.every * 1000), self.tick)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.live.close()

    # --- desenho ----------------------------------------------------------
    def draw(self, s: Step):
        c = self.canvas
        c.delete("all")
        k = s.match.scale if s.match else 1.0
        fs = max(8, round(8 * k))
        if s.status == "lendo":
            self._draw_detection(s, k, fs)
        self._draw_hud(s, k, fs)

    def _box(self, x, y, w, h, color, width=1, dash=None):
        # 2 px por fora da região: nada do overlay cai dentro do que é lido.
        self.canvas.create_rectangle(x - 2, y - 2, x + w + 1, y + h + 1, outline=color, width=width, dash=dash)

    def _draw_detection(self, s: Step, k: float, fs: int):
        c, f, m = self.canvas, s.frame, s.match
        from .anchor import template_box

        self._box(*template_box(m), GOOD, 2)

        for name, (x, y, w, h) in f.rois.items():
            r = f.readings[name]
            self._box(x, y, w, h, _conf_color(r.conf) if r.glyphs else BAD)

        # Valores à direita de tudo o que é capturado, alinhados às linhas do painel.
        cap_right = max(x + w for x, y, w, h in self.live.cap.rects[:1])
        lx = cap_right + round(10 * k)
        rows = [("pop", "idle", "pop", "ociosos"), ("food", "vil_food", "comida", "aldeões"),
                ("wood", "vil_wood", "madeira", "aldeões"), ("gold", "vil_gold", "ouro", "aldeões"),
                ("stone", "vil_stone", "pedra", "aldeões")]
        for a, b, la, lb in rows:
            ra, rb = f.readings[a], f.readings[b]
            va = f.values[a]
            va = f"{va[0]}/{va[1]}" if isinstance(va, tuple) else va
            y = f.rois[a][1] + f.rois[a][3] // 2
            vb = f.values[b]
            text = f"{la} {va if va is not None else '?'} ({ra.conf:.2f})    {lb} {vb if vb is not None else '?'} ({rb.conf:.2f})"
            self._label(lx, y, text, _conf_color(min(ra.conf, rb.conf)), fs)

        x, y, w, h = f.rois["clock"]
        rc = f.readings["clock"]
        secs = f.values["clock"]
        clock = f"{secs // 60:02d}:{secs % 60:02d}" if secs is not None else "--:--"
        self._label(x + w // 2, y + h + round(12 * k), f"relógio {clock} ({rc.conf:.2f})", _conf_color(rc.conf), fs, anchor="n")

        p = f.production
        px, py, pw, ph = p.region
        self._box(px, py, pw, ph, MUTED, dash=(4, 3))
        if p.box:
            bx, by, bw, bh = p.box
            self._box(bx, by, bw, bh, GOOD if p.villager else MUTED, 2 if p.villager else 1)
        text = f"aldeão na fila ({p.score:.2f})" if p.villager else f"TC parado? ({p.score:.2f})"
        self._label(lx, py + round(10 * k), text, GOOD if p.villager else WARN, fs)

    def _label(self, x, y, text, color, fs, anchor="w"):
        c = self.canvas
        t = c.create_text(x, y, text=text, fill=color, font=(FONT, fs, "bold"), anchor=anchor)
        x0, y0, x1, y1 = c.bbox(t)
        bg = c.create_rectangle(x0 - 4, y0 - 2, x1 + 4, y1 + 2, fill=CARD, outline="")
        c.tag_lower(bg, t)

    def _draw_hud(self, s: Step, k: float, fs: int):
        c = self.canvas
        cpu_total, cpu_core = self.cpu.sample()
        status = {
            "aguardando": ("aguardando partida", MUTED),
            "oculto": (f"menu/pausa · forma {s.shape:.2f} · brilho {s.brightness:.0%}", WARN),
            "lendo": ("lendo", GOOD),
        }[s.status]
        lines = [
            ("AoE4 overlay · debug", FG, True),
            (status[0], status[1], False),
            (f"janela {s.win.width}×{s.win.height}", MUTED, False),
        ]
        if s.match:
            lines.append((f"UI {s.match.scale:.2f}× · âncora {s.match.score:.2f}", MUTED, False))
        if s.status == "lendo":
            lines.append((f"leitura {s.read_ms:.0f} ms · captura {s.grab_ms:.0f} ms · a cada {self.every:g} s", MUTED, False))
            if s.bad:
                lines.append(("falhou: " + ", ".join(s.bad), BAD, False))
        lines.append((f"RAM {ram_mb():.0f} MB · CPU {cpu_total:.1f}% ({cpu_core:.0f}% de 1 núcleo)", MUTED, False))
        if not self.excluded:
            lines.append(("aviso: overlay visível na captura", BAD, False))
        for e in self.last_events:
            lines.append((e, MUTED, False))

        x0, y0 = round(16 * k), round(s.win.height * 0.16)
        pad, lh = round(10 * k), round(fs * 1.9)
        width = round(fs * 34)
        height = pad * 2 + lh * len(lines)
        c.create_rectangle(x0, y0, x0 + width, y0 + height, fill=CARD, outline="#262b33")
        c.create_rectangle(x0, y0, x0 + 3, y0 + height, fill=ACCENT, outline="")
        for i, (text, color, bold) in enumerate(lines):
            c.create_text(x0 + pad + 4, y0 + pad + i * lh + lh // 2, text=text, fill=color, anchor="w",
                          font=(FONT, fs + (1 if bold else 0), "bold" if bold else "normal"))


def run(every: float) -> None:
    DebugOverlay(every).run()
