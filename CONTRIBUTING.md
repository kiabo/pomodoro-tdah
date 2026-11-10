# Contribuindo

Obrigado por querer ajudar! O app é feito para pessoas com TDAH, então clareza e pouca fricção valem mais que muitas opções.

## Ambiente

```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
git clone https://github.com/kiabo/pomodoro-tdah && cd pomodoro-tdah
./run.sh
```

Não há dependências Python obrigatórias. `pip install anthropic` só é preciso para a IA na nuvem (opcional).

## Testes

```
scripts/test.sh
```

- `tests/`: lógica pura (timer, banco, planejamento, IA). Não precisam de tela.
- `tests_gtk/`: interface; precisam de uma tela (ou `xvfb-run`).

Rode tudo antes de abrir um PR. O CI roda os mesmos testes.

## Estrutura

- `pomodoro/`: lógica (`timer`, `repository`, `planning`, `controller`, `ai/`) separada da interface (`pomodoro/ui/`).
- `scripts/preview.sh` e `scripts/gallery.sh`: veem as telas com dados de exemplo.
- `pomodoro-tdah.figcraft`: o design de referência.
- `scripts/build-deb.sh`: gera o instalador `.deb`.

## Pull requests

1. Um assunto por PR, com testes quando mexer em lógica.
2. Textos da interface em português do Brasil.
3. Descreva o que mudou e por quê; para mudanças visuais, anexe uma captura (`scripts/preview.sh --png`).

## Lançando uma versão (mantenedores)

1. Atualize `pomodoro/version.py`.
2. Commit, depois `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. O workflow `Release` gera o `.deb` e publica em *Releases*.
