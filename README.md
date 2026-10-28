# aoe4-overlay

Overlay leve para **Age of Empires IV**, no estilo Blitz/Mobalytics. O AoE4 não tem API de estado ao vivo, então o overlay **lê a própria UI do jogo** em regiões pequenas da tela, usando template matching de dígitos (sem OCR pesado), e dá dicas de macro:

- aldeão ocioso
- TC parado (não está produzindo aldeões)
- housed (população no limite)
- recursos acumulados demais

No fim da partida ele gera um **relatório segundo a segundo**: aldeões em cada recurso, estoque, população.

## Princípios
- **Barato**: 1 processo, meta < 50 MB de RAM e < 5 ms por ciclo, lendo 1× por segundo (configurável). Só captura regiões pequenas.
- **Sem configuração**: a resolução vem do Windows e a escala da UI é detectada por âncoras (ícones de recurso e minimapa).
- **Nada de blackbox**: cada etapa tem uma ferramenta de inspeção visual (veja `docs/DECISIONS.md` e o ROADMAP).

## Requisitos
- Windows 10/11, AoE4 em **Borderless** ou **Janela**. Overlays não aparecem em tela cheia exclusiva.
- [uv](https://docs.astral.sh/uv/)

## Uso (até agora)
```powershell
uv sync
uv run aoe4ov window                    # mostra a janela do jogo detectada e a resolução
uv run aoe4ov snap --count 6 --every 20 # salva screenshots da partida em captures/
uv run aoe4ov inspect captures/*.png    # gera .inspect.html: âncora + regiões desenhadas
uv run pytest
```
