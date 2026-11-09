# Pomodoro para TDAH

App de desktop (Python + GTK3) com grupos, tarefas e subtarefas, tempo previsto × real e análise por IA.
O design está em `pomodoro-tdah.figcraft`.

## Dependências do sistema (Ubuntu)

```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
```

`python3-gi-cairo` é necessário para o anel do timer e os gráficos.

## IA

- **Local (sempre disponível, sem internet):** estima tempos a partir do seu histórico previsto × real
  (tarefas parecidas, mesmo grupo, histórico geral) e alimenta a tela Análise.
- **Claude (opcional):** análise em texto, perguntas livres e quebra de tarefas em subtarefas.
  `pip install anthropic`, depois em Configurações → IA e dados: ligue "Usar o Claude", cole a chave
  (ou exporte `ANTHROPIC_API_KEY`) e use "Testar conexão". Só títulos, grupos e tempos são enviados.
  O modelo padrão é `claude-opus-5-5`; dá para trocar por um menor na mesma tela.

## Comandos

| O quê | Como |
|---|---|
| Rodar o app | `./run.sh` |
| Todos os testes | `scripts/test.sh` (os de interface precisam de tela e do `python3-gi-cairo`) |
| Rodar só na bandeja | `./run.sh --hidden` |
| Modo compacto | botão "Modo compacto" na janela, ou pelo ícone da bandeja. Arraste para mover; duplo clique vira pílula; clique direito: menu |
| Ver as telas com dados de exemplo | `scripts/preview.sh [--screen editor\|new-task\|groups\|analysis\|settings[-compact\|-sound\|-ai]\|compact-focus\|-expanded\|-break\|-mini\|-alert\|-rating] [--png arquivo.png]` |
| Galeria de componentes | `scripts/gallery.sh` (ou `--png arquivo.png`) |
| Atalhos | `Ctrl K` busca · `Ctrl N` nova tarefa (modal) · `Ctrl Enter` cria no modal · duplo clique numa tarefa abre o editor · clique direito: menu |

Terminais de apps instalados via snap (ex.: VS Code) injetam bibliotecas que derrubam o PyGObject:
os scripts já limpam o ambiente (`scripts/_cleanenv.sh`). Fora deles, rode num terminal normal do sistema.

Os dados ficam em `~/.local/share/pomodoro-app/` (ou em `POMODORO_DATA_DIR`).
