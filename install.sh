#!/usr/bin/env bash
# Instala "Contas Claude" no menu do usuário a partir da pasta onde o repositório foi clonado.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$data/applications"
icons="$data/icons/hicolor"

# O menu não carrega o PATH do terminal (ex.: Homebrew), então fixa um python3 que tenha Tkinter.
python=""
for p in /usr/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$p" ] && [ -x "$p" ] && "$p" -c 'import tkinter' 2>/dev/null; then python="$p"; break; fi
done
if [ -z "$python" ]; then
  python=/usr/bin/python3
  echo "Aviso: falta o Tkinter. Instale com: sudo apt install python3-tk" >&2
fi

chmod +x "$here/launcher.py"
install -Dm644 "$here/contas-claude.svg" "$icons/scalable/apps/contas-claude.svg"
mkdir -p "$apps"
cat > "$apps/contas-claude.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Contas Claude
Comment=Abra várias contas do Claude ao mesmo tempo
Exec="$python" "$here/launcher.py"
Icon=contas-claude
Terminal=false
Categories=Utility;Network;
StartupWMClass=Contas Claude
EOF

command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$icons" >/dev/null 2>&1 || true
command -v desktop-file-validate >/dev/null && desktop-file-validate "$apps/contas-claude.desktop" || true

echo "Pronto. Procure \"Contas Claude\" no menu de aplicativos."
