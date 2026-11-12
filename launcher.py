#!/usr/bin/env python3
"""Contas Claude: abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo."""
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import unicodedata

HOME = os.path.expanduser("~")
TITLE = "Contas Claude"
LOGIN_WARNING = ("Feche as outras janelas do Claude antes de logar, ou use login por e-mail, "
                 "senão o link do navegador pode cair na conta errada.")


def names_file(home=HOME):
    return os.path.join(home, ".config", "claude-accounts", "accounts.json")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_desktop_exe(home=HOME):
    """Comando do Claude Desktop, ou None. Nunca procura 'claude': esse é o Claude Code."""
    found = shutil.which("claude-desktop")
    if found:
        return [found]
    for pattern in ("/opt/*/claude-desktop", "~/Applications/*laude*.AppImage",
                    "~/.local/bin/*laude*.AppImage", "~/Applications/*laude*.appimage"):
        for path in sorted(glob.glob(pattern.replace("~", home, 1))):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return [path]
    return None


def code_accounts(home=HOME):
    """Pastas do Claude Code com o e-mail e o id da conta logada (só esses campos são lidos)."""
    default = os.path.join(home, ".claude")
    dirs = [default] + sorted(glob.glob(os.path.join(home, ".claude-*")))
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        dirs.append(os.path.abspath(os.path.expanduser(env_dir)))
    result = []
    for d in dict.fromkeys(dirs):
        if not os.path.isdir(d):
            continue
        # Sem CLAUDE_CONFIG_DIR, a conta da pasta padrão fica em ~/.claude.json, fora dela.
        cfg = os.path.join(home, ".claude.json") if d == default else os.path.join(d, ".claude.json")
        acc = read_json(cfg).get("oauthAccount") or {}
        result.append({"dir": d, "email": acc.get("emailAddress"), "uuid": acc.get("accountUuid")})
    return result


def desktop_profiles(home=HOME):
    config = os.path.join(home, ".config")
    dirs = [os.path.join(config, "Claude")] + sorted(glob.glob(os.path.join(config, "Claude-*")))
    return [{"dir": d, "uuid": read_json(os.path.join(d, "config.json")).get("lastKnownAccountUuid")}
            for d in dirs if os.path.isdir(d)]


def detect_accounts(home=HOME):
    """Junta perfis do Desktop e pastas do Code da mesma conta: pelo id da conta, senão pelo sufixo
    (~/.config/Claude-x com ~/.claude-x). Devolve linhas {label, email, desktop, code}."""
    names = read_json(names_file(home))
    code = code_accounts(home)
    profiles = desktop_profiles(home)
    pair = {p["dir"]: next((c for c in code if c["uuid"] and c["uuid"] == p["uuid"]), None) for p in profiles}
    used = {c["dir"] for c in pair.values() if c}
    rows = []
    for p in profiles:
        base = os.path.basename(p["dir"])
        twin = os.path.join(home, ".claude-" + base[len("Claude-"):]) if base != "Claude" else None
        c = pair[p["dir"]]
        if c is None and twin:
            c = next((x for x in code if x["dir"] == twin and x["dir"] not in used
                      and not (x["uuid"] and p["uuid"])), None)
            if c:
                used.add(c["dir"])
            elif not os.path.exists(twin):
                c = {"dir": twin, "email": None}  # Code cria a pasta e pede login na primeira vez
        email = c and c["email"]
        rows.append({"label": names.get(base) or email or base, "email": email,
                     "desktop": p["dir"], "code": c and c["dir"]})
    for c in code:
        if c["dir"] not in used:
            rows.append({"label": c["email"] or os.path.basename(c["dir"]), "email": c["email"],
                         "desktop": None, "code": c["dir"]})
    return rows


def slugify(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_name).strip("-.")


def is_running(profile_dir):
    """O Electron mantém SingletonLock -> 'host-pid' na pasta do perfil enquanto o app está aberto."""
    try:
        pid = int(os.readlink(os.path.join(profile_dir, "SingletonLock")).rsplit("-", 1)[1])
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"claude" in f.read().lower()
    except (OSError, ValueError, IndexError):
        return False


def launch(cmd):
    subprocess.Popen(cmd, start_new_session=True, cwd=HOME, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def terminal_command(code_dir, home=HOME):
    """Terminal que roda o claude com a pasta da conta. None se não houver terminal conhecido."""
    if code_dir == os.path.join(home, ".claude"):
        setup = "unset CLAUDE_CONFIG_DIR"  # pasta padrão: usa também ~/.claude.json
    else:
        setup = "export CLAUDE_CONFIG_DIR=" + shlex.quote(code_dir)
    # O ambiente vai dentro do script: ptyxis e gnome-terminal reusam um processo já aberto.
    script = f"{setup}; cd ~; claude || echo 'Comando claude não encontrado.'; exec bash"
    terminals = [
        ("gnome-terminal", ["--", "bash", "-c", script]),
        ("ptyxis", ["--new-window", "-x", "bash -c " + shlex.quote(script)]),
        ("konsole", ["-e", "bash", "-c", script]),
        ("xfce4-terminal", ["-x", "bash", "-c", script]),
        ("x-terminal-emulator", ["-e", "bash", "-c", script]),
        ("xterm", ["-e", "bash", "-c", script]),
    ]
    for name, args in terminals:
        path = shutil.which(name)
        if path:
            return [path] + args
    return None


def short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


class App:
    def __init__(self, root):
        self.root = root
        self.exe = find_desktop_exe()
        root.title(TITLE)
        root.minsize(480, 0)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Name.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Warn.TLabel", foreground="#a33a00")
        self.body = ttk.Frame(root, padding=16)
        self.body.pack(fill="both", expand=True)
        self.render()

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        if not self.exe:
            ttk.Label(self.body, style="Warn.TLabel", wraplength=440, text=(
                "Claude Desktop não encontrado. Procurei claude-desktop no PATH, em /opt e AppImage "
                "em ~/Applications. Instale o Claude Desktop para usar os botões Desktop.")
            ).pack(fill="x", pady=(0, 12))
        rows = detect_accounts()
        if not rows:
            ttk.Label(self.body, text="Nenhuma conta encontrada. Use \"Adicionar conta\".").pack(anchor="w")
        for row in rows:
            self.account_row(row)
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Adicionar conta", command=self.add_account).pack(side="left")
        ttk.Button(bar, text="Atualizar", command=self.render).pack(side="right")

    def account_row(self, row):
        box = ttk.Frame(self.body, padding=(0, 6))
        box.pack(fill="x")
        ttk.Separator(self.body).pack(fill="x")
        info = ttk.Frame(box)
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=row["label"], style="Name.TLabel").pack(anchor="w")
        where = []
        if row["desktop"]:
            where.append("Desktop " + short(row["desktop"]))
        if row["code"]:
            where.append("Code " + short(row["code"]) + ("" if os.path.isdir(row["code"]) else " (novo login)"))
        ttk.Label(info, text=" · ".join(where), style="Hint.TLabel").pack(anchor="w")
        if row["desktop"]:
            ttk.Button(box, text="Desktop", command=lambda: self.open_desktop(row["desktop"]),
                       state="normal" if self.exe else "disabled").pack(side="left", padx=(8, 0))
        else:
            suggestion = (row["email"] or "").split("@")[0]
            ttk.Button(box, text="Criar Desktop", command=lambda: self.add_account(suggestion),
                       state="normal" if self.exe else "disabled").pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Code", command=lambda: self.open_code(row["code"]),
                   state="normal" if row["code"] else "disabled").pack(side="left", padx=(8, 0))

    def open_desktop(self, profile_dir):
        if is_running(profile_dir):
            messagebox.showinfo(TITLE, "O Claude Desktop desta conta já está aberto.", parent=self.root)
            return
        launch(self.exe + ["--user-data-dir=" + profile_dir])

    def open_code(self, code_dir):
        cmd = terminal_command(code_dir)
        if not cmd:
            messagebox.showerror(TITLE, "Nenhum terminal encontrado (gnome-terminal, ptyxis, konsole...).",
                                 parent=self.root)
            return
        launch(cmd)

    def add_account(self, suggestion=""):
        name = simpledialog.askstring(TITLE, "Nome da nova conta:", initialvalue=suggestion, parent=self.root)
        if not name or not name.strip():
            return
        slug = slugify(name)
        if not slug:
            messagebox.showerror(TITLE, "Use letras ou números no nome.", parent=self.root)
            return
        profile = os.path.join(HOME, ".config", "Claude-" + slug)
        os.makedirs(profile, mode=0o700, exist_ok=True)
        path = names_file()
        names = read_json(path)
        names[os.path.basename(profile)] = name.strip()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False, indent=2)
        self.render()
        messagebox.showwarning(TITLE, LOGIN_WARNING, parent=self.root)
        self.open_desktop(profile)


if __name__ == "__main__":
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk
    except ImportError:
        raise SystemExit("Falta o Tkinter. Instale com: sudo apt install python3-tk")
    # O Tk muda a caixa do className; fixar argv0 deixa WM_CLASS igual ao StartupWMClass do .desktop.
    root = tk.Tk(className=TITLE, useTk=False)
    root.tk.setvar("argv0", TITLE)
    root.loadtk()
    App(root)
    root.mainloop()
