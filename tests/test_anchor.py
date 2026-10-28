from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aoe4ov.anchor import detect, project_rois, to_gray

FIX = Path(__file__).parent / "fixtures"
SHOTS = sorted(FIX.glob("720p_*.png"))
REF_POS = (6, 568)


def _gray(im: Image.Image) -> np.ndarray:
    return to_gray(np.asarray(im.convert("RGB")))


@pytest.mark.parametrize("shot", SHOTS, ids=lambda p: p.name)
def test_detects_anchor_at_reference(shot):
    m = detect(_gray(Image.open(shot)))
    assert m.ok
    assert abs(m.scale - 1.0) < 0.02
    assert (abs(m.x - REF_POS[0]), abs(m.y - REF_POS[1])) <= (1, 1)


@pytest.mark.parametrize("factor", [1.5, 2.0, 3.0], ids=["1080p", "1440p", "4k"])
def test_detects_scale_on_other_resolutions(factor):
    im = Image.open(SHOTS[0])
    big = im.resize((round(im.width * factor), round(im.height * factor)), Image.BICUBIC)
    m = detect(_gray(big))
    assert m.ok
    assert abs(m.scale - factor) / factor < 0.02
    assert abs(m.x - REF_POS[0] * factor) <= 2 * factor
    assert abs(m.y - REF_POS[1] * factor) <= 2 * factor


@pytest.mark.parametrize("ui", [0.8, 1.25])
def test_detects_ui_scale_change(ui):
    """Simula mudar a escala da UI: o painel muda de tamanho, a tela não."""
    im = Image.open(SHOTS[0]).convert("RGB")
    panel = im.crop((0, 555, 135, 720))
    scaled = panel.resize((round(135 * ui), round(165 * ui)), Image.BICUBIC)
    canvas = im.copy()
    canvas.paste(scaled, (0, im.height - scaled.height))
    m = detect(_gray(canvas))
    assert m.ok
    assert abs(m.scale - ui) / ui < 0.02


def test_project_rois_scales_with_anchor():
    m = detect(_gray(Image.open(SHOTS[0])))
    rois = project_rois(m, 1280)
    x, y, w, h = rois["food"]
    assert (abs(x - 28) <= 1, abs(y - 611) <= 1, w, h) == (True, True, 48, 12)


def test_other_window_size_same_ui():
    """Janela 1280x768: a UI do AoE4 não cresce com a altura, a âncora acha mesmo assim."""
    m = detect(_gray(Image.open(FIX / "768p_0648_idle5.png")))
    assert m.ok
    assert abs(m.scale - 1.0) < 0.02
    assert (m.x, m.y) == (6, 616)


def test_rejects_non_game_screen():
    """Captura com outra janela por cima (navegador): confiança tem que ficar baixa."""
    m = detect(_gray(Image.open(FIX / "neg_not_game.png")))
    assert not m.ok


def test_panel_visible_drops_when_panel_hidden():
    """Menu/pausa escondem ou escurecem o painel: a checagem barata tem que perceber."""
    from aoe4ov.anchor import panel_visible

    rgb = np.asarray(Image.open(SHOTS[0]).convert("RGB"))
    m = detect(to_gray(rgb))
    assert panel_visible(rgb, m) > 0.9
    menu = rgb.copy()
    menu[m.y - 10:, :200] = 40  # painel coberto
    assert panel_visible(menu, m) < 0.7


def test_panel_contrast_separates_game_from_menu():
    """Menu/pausa passam um véu (escuro ou azulado) sobre o painel: a forma
    continua, o brilho médio pode até subir, mas o contraste sempre cai.
    Imagens reais das sessões do usuário."""
    from aoe4ov.anchor import panel_state
    from aoe4ov.glyphs import labeled_fixtures

    for png, _ in labeled_fixtures():
        rgb = np.asarray(Image.open(png).convert("RGB"))
        assert panel_state(rgb, detect(to_gray(rgb)))[1] > 0.8, png.name
    for name in ["neg_menu_escuro.png", "neg_menu_veu.png"]:
        rgb = np.asarray(Image.open(FIX / name).convert("RGB"))
        assert panel_state(rgb, detect(to_gray(rgb)))[1] < 0.5, name
    # Tooltip passando por cima do número: o painel está visível de verdade.
    rgb = np.asarray(Image.open(FIX / "tooltip_sobre_pop.png").convert("RGB"))
    assert panel_state(rgb, detect(to_gray(rgb)))[1] > 0.8
