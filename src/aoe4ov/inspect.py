"""Gera um HTML para inspecionar visualmente o pipeline sobre um screenshot.

Mostra a âncora e as regiões sobre a imagem e, para cada região, os estágios
da leitura: recorte → máscara de texto → glifos (caractere + score) → valor.
Também mostra a busca do ícone de aldeão na fila de produção.
"""

from __future__ import annotations

import base64
import html
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import _template, detect, to_gray
from .digits import MIN_SCORE
from .reader import _clock_y_hint, read_frame

ZOOM = 6
GOOD, WARN, BAD = "#3ddc84", "#f5c542", "#ff5c5c"


def _png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _img(arr_or_im, zoom: int = ZOOM) -> str:
    im = arr_or_im if isinstance(arr_or_im, Image.Image) else Image.fromarray(arr_or_im)
    im = im.resize((max(1, im.width * zoom), max(1, im.height * zoom)), Image.NEAREST)
    return f'<img src="data:image/png;base64,{_png_b64(im)}">'


def _color(score: float) -> str:
    return GOOD if score >= 0.85 else WARN if score >= MIN_SCORE else BAD


def build(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img)
    t0 = time.perf_counter()
    m = detect(to_gray(rgb))
    t_anchor = (time.perf_counter() - t0) * 1000
    _clock_y_hint.clear()
    t0 = time.perf_counter()
    f = read_frame(rgb, m)
    t_read = (time.perf_counter() - t0) * 1000

    tpl = _template()
    aw, ah = round(tpl.width * m.scale), round(tpl.height * m.scale)
    acolor = GOOD if m.ok else BAD
    rects = [f'<rect x="{m.x}" y="{m.y}" width="{aw}" height="{ah}" fill="none" stroke="{acolor}" stroke-width="2"/>']

    rows = []
    for name, (x, y, w, h) in f.rois.items():
        r = f.readings[name]
        c = _color(r.conf) if r.glyphs else BAD
        rects.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{c}" stroke-width="1"/>'
            f'<text x="{x}" y="{y - 2}" fill="{c}" font-size="9">{name}</text>'
        )
        crop = rgb[y:y + h, x:x + w]
        mask = (r.mask * 255).astype(np.uint8) if r.mask is not None else np.zeros((h, w), np.uint8)
        glyphs = "".join(
            f'<figure>{_img(np.clip(g.crop, 0, 255).astype(np.uint8), 5)}'
            f'<figcaption><b>{html.escape(g.char)}</b> <span style="color:{_color(g.score)}">{g.score:.2f}</span></figcaption></figure>'
            for g in r.glyphs
        ) or '<span class="muted">nenhum glifo</span>'
        val = f.values.get(name)
        rows.append(
            f"<tr><td><b>{name}</b></td><td>{_img(crop)}</td><td>{_img(mask)}</td>"
            f'<td class="glyphs">{glyphs}</td>'
            f'<td><code>{html.escape(r.text) or "—"}</code></td>'
            f'<td><b style="color:{c}">{html.escape(str(val))}</b></td></tr>'
        )

    p = f.production
    px, py, pw, ph = p.region
    pc = GOOD if p.villager else "#9aa4b2"
    rects.append(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="none" stroke="#9aa4b2" stroke-dasharray="4 3"/>')
    if p.box:
        bx, by, bw, bh = p.box
        rects.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" stroke="{pc}" stroke-width="2"/>')
    prod_crop = _img(rgb[py:py + ph, px:px + pw], 3)

    return f"""<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>Inspect · {html.escape(path.name)}</title>
<style>
 body{{background:#0f1115;color:#e6e6e6;font:14px system-ui,Segoe UI,sans-serif;margin:24px}}
 h1{{font-size:18px}} h2{{font-size:15px;margin-top:28px}} code{{color:#9aa4b2}} .muted{{color:#6b7380}}
 .stats span{{display:inline-block;margin-right:24px}}
 .shot{{position:relative;display:inline-block;max-width:100%}}
 .shot img,.shot svg{{display:block;max-width:100%;height:auto}} .shot svg{{position:absolute;inset:0}}
 table{{border-collapse:collapse;margin-top:12px}} td,th{{padding:6px 10px;border-bottom:1px solid #222;vertical-align:middle;text-align:left}}
 th{{color:#9aa4b2;font-weight:500}}
 img{{image-rendering:pixelated;background:#000}}
 .glyphs{{display:flex;gap:6px}} figure{{margin:0;text-align:center}} figcaption{{font-size:12px}}
</style>
<h1>{html.escape(path.name)} — {img.width}×{img.height}</h1>
<div class="stats">
 <span>Âncora <b style="color:{acolor}">{"OK" if m.ok else "BAIXA CONFIANÇA"}</b> score {m.score:.3f}</span>
 <span>escala <b>{m.scale:.3f}</b>× referência</span>
 <span>detecção <b>{t_anchor:.0f} ms</b></span>
 <span>leitura <b>{t_read:.1f} ms</b></span>
</div>
<p class="muted">Verde ≥ 0,85 · amarelo ≥ {MIN_SCORE} · vermelho = não confiável. Tracejado = onde a fila de produção é procurada.</p>
<div class="shot">
 <img src="data:image/png;base64,{_png_b64(img)}">
 <svg viewBox="0 0 {img.width} {img.height}" font-family="Segoe UI">{"".join(rects)}</svg>
</div>

<h2>Leitura por região</h2>
<table>
<tr><th>campo</th><th>recorte</th><th>máscara de texto</th><th>glifos (caractere · score)</th><th>texto</th><th>valor</th></tr>
{"".join(rows)}
</table>

<h2>Fila de produção</h2>
<p>Aldeão em produção: <b style="color:{pc}">{"SIM" if p.villager else "NÃO"}</b> — melhor match do ícone {p.score:.2f}
(limiar 0,6; parado fica ≤ 0,45 nas capturas reais)</p>
{prod_crop}
</html>"""


def run(paths: list[Path]) -> list[Path]:
    outs = []
    for p in paths:
        out = p.with_suffix(".inspect.html")
        out.write_text(build(p), encoding="utf-8")
        outs.append(out)
    return outs
