# Contas Claude

Abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo no Linux (testado no Ubuntu com GNOME), cada uma com seu próprio login.

## O que faz

- Detecta as contas que já existem: perfis do Claude Desktop em `~/.config/Claude` e `~/.config/Claude-<nome>`, e pastas do Claude Code em `~/.claude` e `~/.claude-<nome>`. Mostra o e-mail da conta quando dá para descobrir.
- **Desktop**: abre o Claude Desktop daquela conta (`--user-data-dir`) em processo separado, então várias contas rodam juntas. Se a conta já estiver aberta, avisa.
- **Code**: abre um terminal com `CLAUDE_CONFIG_DIR` apontando para a pasta da conta e inicia o `claude`.
- **Adicionar conta**: cria `~/.config/Claude-<nome>` e abre o app para você logar.
- Os nomes personalizados ficam em `~/.config/claude-accounts/accounts.json`.

Usa só a biblioteca padrão do Python (Tkinter). Não lê, copia nem grava tokens ou cookies.

## Como instalar

```bash
git clone https://github.com/<usuario>/claude-accounts-launcher.git
cd claude-accounts-launcher
./install.sh
```

Depois procure **Contas Claude** no menu de aplicativos.

Se faltar o Tkinter: `sudo apt install python3-tk`.

## Aviso sobre o login

Feche as outras janelas do Claude antes de logar, ou use login por e-mail, senão o link do navegador pode cair na conta errada.
