"""Gera um HTML para inspecionar visualmente o pipeline sobre um screenshot.

M2: âncora detectada + regiões projetadas desenhadas sobre a imagem, e cada
recorte ampliado. Nas próximas etapas, os estágios da leitura de dígitos entram aqui.
"""

from __future__ import annotations

import base64
import html
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import _template, detect, project_rois, to_gray

ZOOM = 6


def _png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img)
    t0 = time.perf_counter()
    m = detect(to_gray(rgb))
    dt = (time.perf_counter() - t0) * 1000
    rois = project_rois(m, img.width)

    tpl = _template()
    aw, ah = round(tpl.width * m.scale), round(tpl.height * m.scale)
    color = "#3ddc84" if m.ok else "#ff5c5c"

    rects = [
        f'<rect x="{m.x}" y="{m.y}" width="{aw}" height="{ah}" fill="none" stroke="{color}" stroke-width="2"/>'
    ]
    rows = []
    for name, (x, y, w, h) in rois.items():
        rects.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#4da3ff" stroke-width="1"/>'
            f'<text x="{x}" y="{y - 2}" fill="#4da3ff" font-size="9">{name}</text>'
        )
        crop = img.crop((x, y, x + w, y + h)).resize((w * ZOOM, h * ZOOM), Image.NEAREST)
        rows.append(
            f"<tr><td>{name}</td><td><code>{x},{y} {w}×{h}</code></td>"
            f'<td><img src="data:image/png;base64,{_png_b64(crop)}"></td></tr>'
        )

    status = "OK" if m.ok else "BAIXA CONFIANÇA"
    return f"""<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>Inspect · {html.escape(path.name)}</title>
<style>
 body{{background:#0f1115;color:#e6e6e6;font:14px system-ui,Segoe UI,sans-serif;margin:24px}}
 h1{{font-size:18px}} code{{color:#9aa4b2}}
 .stats span{{display:inline-block;margin-right:24px}} .stats b{{color:{color}}}
 .shot{{position:relative;display:inline-block;max-width:100%}}
 .shot img,.shot svg{{display:block;max-width:100%;height:auto}} .shot svg{{position:absolute;inset:0}}
 table{{border-collapse:collapse;margin-top:16px}} td{{padding:6px 12px;border-bottom:1px solid #222}}
 td img{{image-rendering:pixelated;background:#000}}
</style>
<h1>{html.escape(path.name)} — {img.width}×{img.height}</h1>
<div class="stats">
 <span>Âncora: <b>{status}</b></span>
 <span>score <b>{m.score:.3f}</b></span>
 <span>escala <b>{m.scale:.3f}</b> (UI ≈ {m.scale / (img.height / 720) * 100:.0f}%)</span>
 <span>posição <b>{m.x},{m.y}</b></span>
 <span>detecção <b>{dt:.0f} ms</b></span>
</div>
<p>Verde = âncora (coluna de ícones). Azul = regiões que serão lidas.</p>
<div class="shot">
 <img src="data:image/png;base64,{_png_b64(img)}">
 <svg viewBox="0 0 {img.width} {img.height}" font-family="Segoe UI">{"".join(rects)}</svg>
</div>
<table>{"".join(rows)}</table>
</html>"""


def run(paths: list[Path]) -> list[Path]:
    outs = []
    for p in paths:
        out = p.with_suffix(".inspect.html")
        out.write_text(build(p), encoding="utf-8")
        outs.append(out)
    return outs
