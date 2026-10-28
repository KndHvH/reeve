import numpy as np
from PIL import Image

from aoe4ov.anchor import detect, to_gray
from aoe4ov.capture import _union_rects
from aoe4ov.glyphs import labeled_fixtures
from aoe4ov.reader import _clock_y_hint, read_frame
from aoe4ov.window import GameWindow


def test_roi_only_capture_reads_same_as_full_frame():
    """Ao vivo só copiamos dois retângulos; a leitura tem que ser idêntica."""
    for png, _ in labeled_fixtures():
        rgb = np.asarray(Image.open(png).convert("RGB"))
        h, w = rgb.shape[:2]
        m = detect(to_gray(rgb))
        win = GameWindow(0, "AoE4", 0, 0, w, h)
        buf = np.zeros_like(rgb)
        rects = _union_rects(m, win, rgb.shape)
        for x, y, rw, rh in rects:
            buf[y:y + rh, x:x + rw] = rgb[y:y + rh, x:x + rw]

        _clock_y_hint.clear()
        full = read_frame(rgb, m).values
        _clock_y_hint.clear()
        part = read_frame(buf, m).values
        assert part == full, png.name

        captured = sum(rw * rh for _, _, rw, rh in rects)
        assert captured < 0.1 * w * h, "captura deveria ser bem menor que a tela"
