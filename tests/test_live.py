import numpy as np
from PIL import Image

import aoe4ov.capture as capm
import aoe4ov.live as live
from aoe4ov.glyphs import FIXTURES
from aoe4ov.window import GameWindow


class _FakeWin(GameWindow):
    @property
    def foreground(self):
        return True


def test_ui_scale_change_recalibrates_in_same_session(monkeypatch, tmp_path):
    """Mudar a escala da UI nas opções não muda o tamanho da janela: o painel
    "some" da posição esperada. O motor tem que achar de novo e seguir na
    mesma partida, em vez de esperar 30 s e encerrar o log."""
    a = np.asarray(Image.open(FIXTURES / "720p_0217.png").convert("RGB"))
    im = Image.fromarray(a)
    b = im.copy()
    b.paste(im.crop((0, 400, 300, 720)).resize((375, 400), Image.BICUBIC), (0, 320))  # UI 125%
    b = np.asarray(b)

    win = _FakeWin(1, "AoE4", 0, 0, 1280, 720)
    cur = {"f": a}

    def grab(self, w):
        buf = np.zeros_like(cur["f"])
        for x, y, rw, rh in self.rects:
            buf[y:y + rh, x:x + rw] = cur["f"][y:y + rh, x:x + rw]
        return buf

    monkeypatch.setattr(live, "find_game_window", lambda: win)
    monkeypatch.setattr(capm.Capture, "full", lambda self, w: cur["f"])
    monkeypatch.setattr(capm.Capture, "grab", grab)

    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    steps = []
    for frame in [a, a] + [b] * 6:
        cur["f"] = frame
        steps.append(reader.step())
    reader.close()

    assert [s.status for s in steps[:2]] == ["lendo", "lendo"]
    assert steps[2].status == "oculto"
    assert abs(steps[-1].match.scale - 1.25) < 0.03
    assert steps[-1].status == "lendo"
    assert steps[-1].frame.values["pop"] == (10, 40)
    assert steps[-1].frame.values["food"] == 100
    assert len(list(tmp_path.iterdir())) == 1, "deveria continuar na mesma sessão"
