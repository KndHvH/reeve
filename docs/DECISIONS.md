# Decisões técnicas

Registro curto de cada escolha e do motivo, para poder ser questionada e ajustada.

| Data | Decisão | Motivo |
|------|---------|--------|
| 2026-10-28 | Python 3.13 + tkinter desenhado em Canvas (sem widgets nativos) | Menor RAM possível (~30 MB). Canvas permite um visual moderno sem Qt/Electron. |
| 2026-10-28 | Template matching de dígitos em vez de OCR | A fonte do jogo é fixa. ~1 ms por leitura vs dezenas de ms (Tesseract) ou centenas de MB (EasyOCR). |
| 2026-10-28 | Captura só de ROIs com `mss`, a 2 Hz | Nenhum alerta precisa de mais que isso; capturar a tela inteira desperdiça CPU. |
| 2026-10-28 | Resolução via `GetClientRect` (ctypes) e escala da UI via âncoras multi-escala | Sem perfis fixos por resolução. A detecção roda uma vez e se refaz se a confiança cair. |
| 2026-10-28 | Processo DPI-aware (`SetProcessDpiAwareness(2)`) | Senão, com a escala do Windows ≠ 100%, as coordenadas vêm virtualizadas e as ROIs erram. |
| 2026-10-28 | "TC parado" por heurística: total de aldeões sem subir por > ~22 s | Sem o TC selecionado a fila não é visível. Um aldeão leva 20 s. |
