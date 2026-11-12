# Contas Claude

Abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo no Linux (testado no Ubuntu com GNOME), cada uma com seu próprio login.

## O que faz

- Detecta as contas que já existem: perfis do Claude Desktop em `~/.config/Claude` e `~/.config/Claude-<nome>`, e pastas do Claude Code em `~/.claude` e `~/.claude-<nome>`. Mostra o e-mail da conta quando dá para descobrir.
- **Desktop**: abre o Claude Desktop daquela conta (`--user-data-dir`) em processo separado, então várias contas rodam juntas. Se a conta já estiver aberta, avisa.
- **Code**: abre um terminal com `CLAUDE_CONFIG_DIR` apontando para a pasta da conta e inicia o `claude`.
- **Adicionar conta**: cria `~/.config/Claude-<nome>` e abre o app para você logar.
- **Criar Desktop** (conta que só tem Claude Code): cria um perfil novo e, se essa conta já foi usada em outro perfil do Desktop, copia as sessões dela (`claude-code-sessions/<conta>` e `local-agent-mode-sessions/<conta>`) e os skills compartilhados (`local-agent-mode-sessions/skills-plugin`). O perfil antigo não é alterado. Worktrees, preferências e hosts SSH não são copiados: o Desktop do perfil novo poderia tratar as worktrees do outro perfil como órfãs e removê-las.
- Os nomes personalizados ficam em `~/.config/claude-accounts/accounts.json`.

Usa só a biblioteca padrão do Python (Tkinter). Não lê, copia nem grava tokens ou cookies: o login é sempre feito de novo no perfil novo.

## Como instalar

```bash
git clone https://github.com/<usuario>/claude-accounts-launcher.git
cd claude-accounts-launcher
./install.sh
```

Depois procure **Contas Claude** no menu de aplicativos.

Se faltar o Tkinter: `sudo apt install python3-tk`.

## Aviso sobre o login

- Entre só com **Continuar com Google**. Não use login por e-mail: esse link pode cair na janela de outra conta e trocar a conta dela.
- O retorno do login pelo navegador (links `claude://`) normalmente vai para o perfil padrão do Claude Desktop. Por isso, ao abrir um perfil que ainda não tem login, o Contas Claude faz do atalho `contas-claude-login.desktop` o único app de `claude://` no `~/.config/mimeapps.list`, apontando para a janela nova. Com um app só, o portal do sistema (usado pelo Firefox em snap) também entrega direto, sem a janela "Abrir com". Quando o login termina, a janela fecha ou passam 15 minutos, tudo volta exatamente como era.
- Deixe o Contas Claude aberto até terminar o login. Se ele cair no meio, o estado anterior fica em `~/.config/claude-accounts/routing.json` e é restaurado na próxima vez que ele abrir, ou no próximo login do computador (por um autostart que se apaga sozinho).
- Com duas contas abertas, feche cada uma pelo X da janela dela. No GNOME as duas ficam no mesmo ícone, e "Sair" no ícone fecha todas.
- Um Claude Desktop aberto com outro perfil regrava `~/.config/Claude/os-entry-points.json`, que a busca do GNOME usa para listar as sessões do perfil padrão. A busca pode parar de mostrá-las até o perfil padrão ser reaberto. Nada se perde.
