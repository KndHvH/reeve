"""Leitura ao vivo de uma partida: o motor usado pelo `watch` e pelo overlay.

Cada `step()` faz um ciclo: acha a janela, calibra a âncora quando precisa,
captura só as regiões, confere se o painel está visível (menu/pausa) e lê.
Também grava a partida em sessions/<início>/ (log.jsonl + imagens das
leituras que falham), então quem usa o motor só cuida de mostrar o resultado.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import MIN_SCORE, AnchorMatch, panel_state
from .capture import Capture
from .reader import Frame, read_frame
from .window import GameWindow, find_game_window

MAX_FAIL_SHOTS = 30  # imagens de falha salvas por partida
HIDDEN_END_S = 30    # painel oculto por mais que isso = fim de partida
DIM_RATIO = 0.7      # âncora abaixo de 70% do brilho normal = tela escurecida (menu)
SHAPE_RATIO = 0.85   # forma da âncora abaixo de 85% da calibração = painel coberto/esmaecendo
RECAL_EVERY = 3      # com o painel sumido, procura de novo a cada 3 ciclos (escala da UI mudou?)


@dataclass
class Step:
    status: str                       # "sem_jogo" | "aguardando" | "oculto" | "lendo"
    win: GameWindow | None = None
    match: AnchorMatch | None = None
    frame: Frame | None = None
    bad: list[str] = field(default_factory=list)
    grab_ms: float = 0.0
    read_ms: float = 0.0
    shape: float = 0.0                # forma da âncora neste ciclo
    brightness: float = 1.0           # brilho relativo ao normal da partida
    events: list[str] = field(default_factory=list)  # mensagens para quem mostra


class LiveReader:
    def __init__(self, every: float, sessions_dir: Path = Path("sessions")):
        self.every = every
        self.sessions_dir = sessions_dir
        self.cap = Capture()
        self.match: AnchorMatch | None = None
        self.size: tuple[int, int] | None = None
        self.fails = 0
        self.hidden = 0
        self.ref_bright = 0.0  # brilho da âncora na partida (o maior visto)
        self.session: Path | None = None
        self.log = None
        self.saved_fails = 0

    # --- sessão -----------------------------------------------------------
    def _open_session(self, events: list[str]) -> None:
        if self.log is None:
            self.session = self.sessions_dir / f"{datetime.now():%Y%m%d-%H%M%S}"
            self.session.mkdir(parents=True, exist_ok=True)
            self.log = open(self.session / "log.jsonl", "a", encoding="utf-8")
            self.saved_fails = 0
            events.append(f"gravando em {self.session}")

    def close(self, events: list[str] | None = None) -> None:
        if self.log:
            self.log.close()
            if events is not None:
                events.append(f"log salvo em {self.session}")
        self.session, self.log = None, None

    def _write(self, obj: dict) -> None:
        self.log.write(json.dumps({"wall": f"{datetime.now():%H:%M:%S}", **obj}, ensure_ascii=False) + "\n")
        self.log.flush()

    # --- ciclo ------------------------------------------------------------
    def step(self) -> Step:
        events: list[str] = []
        win = find_game_window()
        if win is None or not win.foreground:
            return Step("sem_jogo", win)

        if self.match is None or self.size != (win.width, win.height) or self.fails >= 3:
            self.match = self.cap.calibrate(win)
            self.size = (win.width, win.height)
            self.fails = 0
            if not self.match.ok:
                # Menu, tela de carregamento ou fim de partida: sem painel na tela.
                self.close(events)
                m, self.match = self.match, None
                return Step("aguardando", win, m, events=events)
            events.append(f"painel encontrado: score {self.match.score:.3f} escala {self.match.scale:.3f}")
            self.ref_bright = 0.0
            self._open_session(events)

        match = self.match
        t0 = time.perf_counter()
        buf = self.cap.grab(win)
        grab_ms = (time.perf_counter() - t0) * 1000

        # Menu, pausa ou tela de fim escondem o painel (forma some) ou escurecem
        # a tela (forma fica, brilho cai): pula a leitura em vez de registrar lixo.
        shape, bright = panel_state(buf, match)
        rel = bright / self.ref_bright if self.ref_bright else 1.0
        if shape >= max(MIN_SCORE, SHAPE_RATIO * match.score) and rel >= DIM_RATIO:
            self.ref_bright = max(self.ref_bright, bright)
        else:
            if self.hidden == 0:
                self._write({"event": "painel_oculto", "forma": round(shape, 3), "brilho": round(rel, 2)})
            self.hidden += 1
            # Painel "sumido" pode ser só a escala da UI que mudou nas opções
            # (a janela não muda de tamanho): procura de novo de tempos em tempos
            # e, se achar em outro lugar/escala, segue na mesma partida.
            if self.hidden % RECAL_EVERY == 0:
                new = self.cap.probe(win)
                moved = abs(new.scale - match.scale) > 0.01 * match.scale or abs(new.x - match.x) + abs(new.y - match.y) > 2
                if new.ok and moved:
                    self.cap.adopt(new, win)
                    self.match, self.hidden, self.ref_bright = new, 0, 0.0
                    self._write({"event": "recalibrado", "anchor": [new.x, new.y, round(new.scale, 3), round(new.score, 3)]})
                    events.append(f"painel mudou: recalibrado (escala {new.scale:.3f})")
                    return Step("oculto", win, new, grab_ms=grab_ms, shape=shape, brightness=rel, events=events)
            if self.hidden * self.every >= HIDDEN_END_S:
                self.close(events)
                self.match, self.hidden = None, 0
            return Step("oculto", win, match, grab_ms=grab_ms, shape=shape, brightness=rel, events=events)
        if self.hidden:
            self._write({"event": "painel_visivel"})
            self.hidden = 0

        t1 = time.perf_counter()
        f = read_frame(buf, match)
        read_ms = (time.perf_counter() - t1) * 1000
        bad = [n for n, r in f.readings.items() if not r.ok]
        self.fails = self.fails + 1 if len(bad) > 3 else 0

        self._write({
            "values": f.values,
            "text": {n: r.text for n, r in f.readings.items()},
            "conf": {n: round(r.conf, 3) for n, r in f.readings.items()},
            "prod_score": round(f.production.score, 3),
            "anchor": [match.x, match.y, round(match.scale, 3), round(match.score, 3)],
            "ms": round(grab_ms + read_ms, 1),
            "grab_ms": round(grab_ms, 1),
        })
        if bad and self.saved_fails < MAX_FAIL_SHOTS:
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"falha_{datetime.now():%H%M%S}_{'-'.join(bad)}.png")
            self.saved_fails += 1
        return Step("lendo", win, match, f, bad, grab_ms, read_ms, shape, rel, events)
