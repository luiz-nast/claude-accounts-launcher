# Contas Claude

Abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo no Linux (testado no Ubuntu com GNOME), cada uma com seu próprio login.

## O que faz

- Detecta as contas que já existem: perfis do Claude Desktop em `~/.config/Claude` e `~/.config/Claude-<nome>`, e pastas do Claude Code em `~/.claude` e `~/.claude-<nome>`. Mostra o e-mail da conta quando dá para descobrir.
- **Desktop**: abre o Claude Desktop daquela conta (`--user-data-dir`) em processo separado, então várias contas rodam juntas. Se a conta já estiver aberta, avisa.
- **Code**: abre um terminal com `CLAUDE_CONFIG_DIR` apontando para a pasta da conta e inicia o `claude`.
- **Adicionar conta**: cria `~/.config/Claude-<nome>` e abre o app para você logar.
- **Criar Desktop** (conta que só tem Claude Code): cria um perfil novo e, se essa conta já foi usada em outro perfil do Desktop, copia as sessões dela. O perfil antigo não é alterado. Worktrees, preferências e hosts SSH não são copiados: o Desktop do perfil novo poderia tratar as worktrees do outro perfil como órfãs e removê-las.
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
- O retorno do login pelo navegador (links `claude://`) normalmente vai para o perfil padrão do Claude Desktop. Por isso, ao abrir um perfil que ainda não tem login, o Contas Claude manda esses links para a janela nova até o login terminar, e depois devolve tudo como estava. Isso inclui a escolha guardada pelo portal do sistema, que é o que o Firefox em snap usa. Deixe o Contas Claude aberto até terminar o login.
- Com duas contas abertas, feche cada uma pelo X da janela dela. No GNOME as duas ficam no mesmo ícone, e "Sair" no ícone fecha todas.
