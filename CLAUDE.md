# aoe4-overlay

Overlay para AoE4 que lê a UI do jogo por template matching. Veja `README.md`, `ROADMAP.md` e `docs/DECISIONS.md`.

## Regras do projeto
- **Custo computacional é requisito**: sem deps pesadas (torch, OCR, Qt, Electron), sem captura de tela inteira no loop, loop padrão de 1 leitura/s (configurável até 1 a cada 2 s), redesenhar o overlay só quando o estado mudar. Em caso de dúvida, consulte o agente `perf-guardian`.
- **Nada hardcoded por resolução**: ROIs ficam em `assets/layout.json` em coordenadas de referência (1080p, UI 100%) relativas a uma âncora, escaladas em runtime.
- **Tudo inspecionável**: cada etapa nova do pipeline precisa de uma saída visual (`inspect.html`, `--debug`) para o usuário validar.
- **Marcos com checkpoint**: entregar um marco do ROADMAP, pedir a validação do usuário e só então seguir.
- Registrar decisões não óbvias em `docs/DECISIONS.md`.
- Usar só ctypes para Win32 (sem pywin32). Comentários e mensagens em português.

## Comandos
- `uv sync`, `uv run pytest`, `uv run aoe4ov <cmd>`
