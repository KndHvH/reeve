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
| 2026-10-28 | Só capturar com o AoE4 em primeiro plano (`GetForegroundWindow`) | O `mss` copia a tela, não a janela: com o navegador por cima, saiu um print do YouTube. A âncora já rejeitava (score 0,42), mas não faz sentido capturar. |
| 2026-10-28 | Não assumir que a escala da UI acompanha a altura da janela | Em 1280x720 e 1280x768 a UI tem exatamente o mesmo tamanho em pixels. A âncora mede a escala real, então o código só usa a altura como palpite inicial. |
| 2026-10-28 | Glifo normalizado em 16×24 com 1 px de margem de contexto, sem desfoque | Comparado por leave-one-out nas 8 fixtures: 144/144 glifos certos (8×12 sem margem errava e dava score 0,55 em dígitos certos por causa de subpixel). |
| 2026-10-28 | Dígitos encostados ("40", "/40" em 720p) são quebrados na coluna mais fraca quando o bloco passa de 7,5 px × escala | A projeção por colunas sozinha juntava esses glifos. |
| 2026-10-28 | Banco de glifos = amostras reais rotuladas (`assets/glyphs/<char>/*.png`), não uma fonte desenhada | Dá para abrir a pasta e ver a referência. Cresce com cada captura rotulada no `aoe4ov label`. |
| 2026-10-28 | Relógio: janela deslizante na vertical, escolhe a posição válida de **maior confiança** (dígitos com alturas iguais) | O relógio desce na troca de era (relato do usuário). A primeira posição válida cortava 1 px do topo ('2' virava '7'); ordenar por altura pegava textura de construção ("5045"). |
| 2026-10-28 | Fila de produção: NCC do ícone de aldeão acima do painel, limiar 0,6 | Nas capturas: parado ≤ 0,43, produzindo ≥ 0,70 (o pior caso tem o "3" de contagem por cima). O ícone de tecnologia com aldeão (fundo marrom) dá ~0,40. |
| 2026-10-28 | Ao vivo, captura só 2 retângulos (canto inferior esquerdo + relógio), ~5% da tela | Teste garante que a leitura é idêntica à da tela inteira. |
| 2026-10-28 | Custo atual por leitura: ~11 ms (≈7 ms são a fila de produção); relógio sem cache confiável ~50 ms | Aceitável a 1 leitura/s (~1% de um núcleo). Otimização pendente para o `perf-guardian`: região da fila menor ou checagem a cada 2–3 s. |
| 2026-10-28 | Relógio usa máscara por **contraste local** (pixel − média da vizinhança > 60), o painel continua com brilho absoluto | Na troca de era o relógio desceu para cima da areia da praia; a areia clara, vista pelo fundo translúcido, entrava na máscara e a leitura virava um "4:08:53" falso. No painel o fundo é sempre escuro e os zeros apagados precisam do limiar absoluto. |
| 2026-10-28 | Relógio: em cada posição da janela ficam só glifos com o mesmo topo/altura da maioria | Bordas da caixa contra uma construção clara viravam traços lidos como "1" (score 0,7–0,8). |
| 2026-10-28 | Região do relógio aumentada para 84 px de altura (ref.) | Na troca de era o relógio desce ~31 px; folga para escalas maiores. |
