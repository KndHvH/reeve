# Decisões técnicas

Registro curto de cada escolha e do motivo, para poder ser questionada e ajustada.

| Data | Decisão | Motivo |
|------|---------|--------|
| 2026-10-28 | Python 3.13 + tkinter desenhado em Canvas (sem widgets nativos) | Menor RAM possível (~30 MB). Canvas permite um visual moderno sem Qt/Electron. |
| 2026-10-28 | Template matching de dígitos em vez de OCR | A fonte do jogo é fixa. ~1 ms por leitura vs dezenas de ms (Tesseract) ou centenas de MB (EasyOCR). |
| 2026-10-28 | Captura só de ROIs com `mss`, 1 leitura/s (configurável, 1–2 s) | Pedido do usuário: nada precisa ser instantâneo. Capturar a tela inteira desperdiça CPU. |
| 2026-10-28 | Resolução via `GetClientRect` (ctypes) e escala da UI via âncoras multi-escala | Sem perfis fixos por resolução. A detecção roda uma vez e se refaz se a confiança cair. |
| 2026-10-28 | Processo DPI-aware (`SetProcessDpiAwareness(2)`) | Senão, com a escala do Windows ≠ 100%, as coordenadas vêm virtualizadas e as ROIs erram. |
| 2026-10-28 | "TC parado" por heurística: total de aldeões sem subir por > ~22 s | Sem o TC selecionado a fila não é visível. Um aldeão leva 20 s. |
| 2026-10-28 | Âncora = coluna de ícones do painel (casa/comida/madeira/ouro/pedra), recortada de `tests/fixtures/720p_0036.png` | Alta e de forma única: fixa bem a escala. Score 0,996 nas capturas reais. |
| 2026-10-28 | Detecção em 2 passos: varredura grossa em 360p + refino na resolução original | Primeira versão levava 0,6 s (720p) a 5,8 s (4K). Agora 37 ms (720p) a 133 ms (4K), roda só uma vez. |
| 2026-10-28 | Referência = 720p (a resolução do usuário), não 1080p | Os templates vêm das capturas reais. Em telas maiores a âncora é ampliada, e o NCC tolera bem. |
| 2026-10-28 | Relógio: região relativa ao centro do topo, escalada pela mesma escala do painel | Ainda **não validado** com outra escala de UI. O fundo do relógio é semitransparente e marcadores de caminho (pontos amarelos) podem cair dentro da região: a leitura vai filtrar por cor/forma e checar que o tempo só avança. |
| 2026-10-28 | "TC parado": usar a fila de produção acima do painel (ícone de aldeão + barra de progresso) como sinal principal; a heurística dos 22 s fica de reserva | Sugestão do usuário: a fila aparece sem precisar selecionar o TC. |
