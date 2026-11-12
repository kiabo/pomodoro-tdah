# Pomodoro para TDAH

App de desktop (Python + GTK3) com grupos, tarefas e subtarefas, tempo previsto × real e análise por IA.
O design está em `pomodoro-tdah.figcraft`.

## Instalação (Ubuntu / Debian e derivados)

Baixe o `.deb` mais recente em [Releases](../../releases/latest) e instale:

```
sudo apt install ./pomodoro-tdah_*_all.deb
```

O `apt` instala as dependências sozinho. Depois é só procurar "Pomodoro TDAH" no menu de aplicativos,
ou rodar `pomodoro-tdah`. Para atualizar, baixe o `.deb` novo e rode o mesmo comando.
Para remover: `sudo apt remove pomodoro-tdah` (seus dados em `~/.local/share/pomodoro-app/` são mantidos).

Quer ajudar? Veja o [CONTRIBUTING.md](CONTRIBUTING.md).

## Rodar a partir do código-fonte

### Dependências do sistema (Ubuntu)

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

## Jira (Cloud)

O Jira é um espelho: o app lê as suas issues e você organiza do seu jeito, com subtarefas, notas e previsão
só locais. **Nada é enviado ao Jira sem você pedir e confirmar numa janela que mostra exatamente o que vai.**

1. Crie um token em id.atlassian.com → Segurança → Tokens de API.
2. Em Configurações → Jira, informe o endereço (`https://empresa.atlassian.net`), o e-mail da conta e o token
   (ou exporte `JIRA_API_TOKEN`) e use "Testar conexão".
3. "Importar issues…" mostra o que vai entrar, **um bloco por épico (recolhido)**: abra os que interessam, desmarque o
   que não quer e veja no botão quantos itens serão importados. Em "O que trazer" você escolhe entre "Minhas + criadas
   por mim + sem responsável" (padrão; muita coisa útil fica sem responsável no Jira), "Só atribuídas a mim" ou a sua
   própria busca (JQL).
   As tarefas ganham o selo `ABC-123`, e o editor mostra o tipo da issue (Tarefa, Bug…) e o épico.

**Épicos e hierarquia:** cada épico vira um **grupo** do app e as tarefas dele entram nesse grupo (o épico em si não
vira tarefa; o grupo ganha o nome dele e, depois, o nome é seu). Sub-tarefas do Jira viram **subtarefas locais** da
tarefa-pai. O que não tem épico vai para o grupo que você escolher para cada projeto (ou "Jira"). O épico vem junto da
filha, então até épicos já resolvidos aparecem como grupo se ainda houver tarefa aberta nele.

Para escrever no Jira, abra a tarefa no editor: a faixa "Jira" sob o título tem **um botão "Enviar ao Jira ▾"** com
as ações abaixo. Cada uma abre uma janela mostrando exatamente o que vai, e só envia se você confirmar.

- **Comentar com as minhas notas**: entra como comentário novo; nada que já existe na issue é alterado.
- **Atualizar título e previsão**: mostra o que está no Jira × o que vai, e você marca o que enviar.
- **Mudar status…**: lista as transições que o fluxo do seu projeto permite. Ao concluir uma tarefa ligada ao
  Jira, o app também pergunta se quer mover a issue (dizer não não muda nada lá).

- **Lançar tempo**: manda o tempo cronometrado aqui como worklog, um lançamento por dia (você marca os dias).
  Cada sessão só é lançada uma vez, então dá para lançar de novo depois sem duplicar. Dias com menos de 1 minuto
  ficam de fora, porque o Jira não aceita.
- **Criar subtarefas no Jira**: transforma subtarefas locais em sub-tarefas da issue. As desmarcadas, e todas por
  padrão, continuam só locais. A subtarefa criada ganha a chave (`ABC-12`), mas concluir uma aqui não conclui lá.
- **Trazer subtarefas de lá**: o caminho inverso, só leitura: cria subtarefas locais a partir das que já existem
  na issue.

Cada envio confirmado fica registrado ("Último envio…"). Se o Jira recusar, nada é registrado e o motivo aparece.

**Atualizar sozinho** (Configurações → Jira, desligado por padrão): a cada 15, 30 ou 60 minutos o app relê o Jira
e atualiza o que você já importou. É só leitura: issues novas apenas avisam ("importe em Configurações"), e nada é
escrito no Jira. Se o Jira pedir para esperar (limite de requisições), o app espera e tenta de novo.

**Divergências:** se o Jira mudou o título ou a previsão *e* você já tinha mudado o seu, o seu é mantido e o cartão
avisa, com "Usar o do Jira" ou "Manter o meu". Enviar o campo ao Jira também resolve. No modo compacto, a chave da
issue (`ABC-123`) aparece abaixo do título da tarefa em foco.

Atualizar repete o mesmo caminho: o título só acompanha o Jira enquanto você não o renomear, e issues que saem da
sua lista ficam marcadas, sem apagar a tarefa.

## Comandos

| O quê | Como |
|---|---|
| Rodar o app | `./run.sh` |
| Todos os testes | `scripts/test.sh` (os de interface precisam de tela e do `python3-gi-cairo`) |
| Gerar o instalador `.deb` | `scripts/build-deb.sh` (saída em `dist/`) |
| Rodar só na bandeja | `./run.sh --hidden` |
| Modo compacto | botão "Modo compacto" na janela, ou pelo ícone da bandeja. Arraste para mover; duplo clique vira pílula; clique direito: menu |
| Ver as telas com dados de exemplo | `scripts/preview.sh [--screen editor\|editor-jira\|new-task\|groups\|analysis\|settings[-compact\|-sound\|-ai\|-jira]\|compact-focus\|-expanded\|-break\|-mini\|-alert\|-rating] [--png arquivo.png]` |
| Galeria de componentes | `scripts/gallery.sh` (ou `--png arquivo.png`) |
| Atalhos | `Ctrl K` busca · `Ctrl N` nova tarefa (modal) · `Ctrl Enter` cria no modal · duplo clique numa tarefa abre o editor · clique direito: menu |

Terminais de apps instalados via snap (ex.: VS Code) injetam bibliotecas que derrubam o PyGObject:
os scripts já limpam o ambiente (`scripts/_cleanenv.sh`). Fora deles, rode num terminal normal do sistema.

Os dados ficam em `~/.local/share/pomodoro-app/` (ou em `POMODORO_DATA_DIR`).

## Atalhos

| Tecla | Ação |
|---|---|
| Ctrl K | Buscar tarefa |
| Ctrl N | Nova tarefa |
| Ctrl Enter | Criar a tarefa (no modal Nova tarefa) |
| Espaço | Pausar / retomar o timer (fora de campos de texto e botões) |
| Esc | Voltar para Hoje (ou fechar o modal / a lista do modo compacto) |

## Licença

[MIT](LICENSE).
