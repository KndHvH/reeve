# Roadmap

## v0.1: MVP (dicas independentes de build)
Cada marco termina com uma validação visual feita pelo usuário antes de seguir para o próximo.

| # | Entrega | Validação | Status |
|---|---------|-----------|--------|
| M1 | Repo, scaffold, agentes, detecção da janela, `snap` | `aoe4ov window` mostra a resolução certa | ✅ |
| M2 | Âncora + escala da UI (multi-escala) | `inspect.html` com a caixa da âncora nos screenshots | ✅ |
| M3 | Leitura de dígitos (recursos, aldeões/recurso, pop, relógio, ociosos) + fila de produção | `inspect.html` por estágio + rotulador + `watch` ao vivo + testes | 🔎 aguardando validação |
| M4 | Overlay `--debug` ao vivo | Caixas e valores por cima do jogo numa partida vs IA | |
| M5 | Regras: ocioso, TC parado, housed, banco flutuando | Forçar cada situação e ver o alerta | |
| M6 | Recorder JSONL + `report.html` auditável | Conferir a timeline contra o replay | |

## v0.2: Execução vs build
Diff por timestamp: aldeões e recursos esperados vs reais.

## v0.3: Builds
Importar (aoe4guides / JSON próprio), criar e editar.

## v0.4: Build "inteligente"
Simulador de economia: dado o nº de aldeões por recurso e as taxas de coleta (civ, techs como Wheelbarrow e Double Broadaxe), projeta os recursos disponíveis no tempo T. O editor valida se cada passo da build é alcançável.

## Depois
- Idiomas (só afeta textos: dígitos e ícones são universais).
