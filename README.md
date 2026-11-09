# Pomodoro para TDAH

App de desktop (Python + GTK3) com grupos, tarefas e subtarefas, tempo previsto × real e análise por IA.
O design está em `pomodoro-tdah.figcraft`.

## Dependências do sistema (Ubuntu)

```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
```

`python3-gi-cairo` é necessário para o anel do timer e os gráficos.

## Comandos

| O quê | Como |
|---|---|
| Rodar o app | `./run.sh` |
| Todos os testes | `scripts/test.sh` (os de interface precisam de tela e do `python3-gi-cairo`) |
| Galeria de componentes | `scripts/gallery.sh` (ou `--png arquivo.png`) |

Terminais de apps instalados via snap (ex.: VS Code) injetam bibliotecas que derrubam o PyGObject:
os scripts já limpam o ambiente (`scripts/_cleanenv.sh`). Fora deles, rode num terminal normal do sistema.

Os dados ficam em `~/.local/share/pomodoro-app/` (ou em `POMODORO_DATA_DIR`).
