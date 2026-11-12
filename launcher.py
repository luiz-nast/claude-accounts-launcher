#!/usr/bin/env python3
"""Contas Claude: abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo."""
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import unicodedata

HOME = os.path.expanduser("~")
TITLE = "Contas Claude"
LOGIN_WARNING = ("Deixe o Contas Claude aberto até terminar o login: enquanto isso, o retorno do navegador "
                 "vai só para esta janela nova, sem mexer nas contas que já estão abertas.")
LINK_TYPE = "x-scheme-handler/claude"
LOGIN_HANDLER = "contas-claude-login.desktop"
APP_HANDLER = "com.anthropic.Claude.desktop"
# Setup que vai para um perfil novo. Login (Cookies, config.json, Local Storage, tokens de SSH) nunca é copiado;
# as pastas temporárias das sessões ficam onde estão, porque as sessões guardam o caminho completo delas.
ACCOUNT_DIRS = ("claude-code-sessions", "local-agent-mode-sessions")
SHARED_SETUP = ("claude_desktop_config.json", "git-worktrees.json", "git-shadow", "ssh_configs.json",
                "claude-ssh-remote", os.path.join("local-agent-mode-sessions", "skills-plugin"))


def names_file(home=HOME):
    return os.path.join(home, ".config", "claude-accounts", "accounts.json")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def saved_profiles(home=HOME):
    """accounts.json: {pasta do perfil: {"name": nome escolhido, "account": id da conta}}."""
    return {k: v if isinstance(v, dict) else {"name": v} for k, v in read_json(names_file(home)).items()}


def save_profile(base, name, account=None, home=HOME):
    path = names_file(home)
    data = read_json(path)
    data[base] = {"name": name, "account": account} if account else {"name": name}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def logged_account(profile_dir):
    """Id da conta que já logou neste perfil do Desktop, ou None."""
    return read_json(os.path.join(profile_dir, "config.json")).get("lastKnownAccountUuid")


def desktop_profiles(home=HOME):
    config = os.path.join(home, ".config")
    meta = saved_profiles(home)
    dirs = [os.path.join(config, "Claude")] + sorted(glob.glob(os.path.join(config, "Claude-*")))
    return [{"dir": d, "uuid": logged_account(d) or meta.get(os.path.basename(d), {}).get("account")}
            for d in dirs if os.path.isdir(d)]


def detect_accounts(home=HOME):
    """Junta perfis do Desktop e pastas do Code da mesma conta: pelo id da conta, senão pelo sufixo
    (~/.config/Claude-x com ~/.claude-x). Devolve linhas {label, email, account, desktop, code}."""
    meta = saved_profiles(home)
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
        rows.append({"label": meta.get(base, {}).get("name") or email or base, "email": email,
                     "account": p["uuid"], "desktop": p["dir"], "code": c and c["dir"]})
    for c in code:
        if c["dir"] not in used:
            rows.append({"label": c["email"] or os.path.basename(c["dir"]), "email": c["email"],
                         "account": c["uuid"], "desktop": None, "code": c["dir"]})
    return rows


def copy_setup(account, dest, home=HOME):
    """Copia para dest o setup desta conta guardado em outro perfil do Desktop (sessões, pastas, preferências).
    Só copia o que ainda não existe em dest; a origem não é alterada. Devolve a pasta de origem ou None."""
    for p in desktop_profiles(home):
        src = p["dir"]
        if src == dest or not any(os.path.isdir(os.path.join(src, d, account)) for d in ACCOUNT_DIRS):
            continue
        for rel in [os.path.join(d, account) for d in ACCOUNT_DIRS] + list(SHARED_SETUP):
            s, t = os.path.join(src, rel), os.path.join(dest, rel)
            if os.path.lexists(t) or not os.path.exists(s):
                continue
            os.makedirs(os.path.dirname(t), exist_ok=True)
            if os.path.isdir(s):
                shutil.copytree(s, t, symlinks=True)
            else:
                shutil.copy2(s, t)
        return src
    return None


def slugify(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_name).strip("-.")


def create_profile(name, account=None, home=HOME):
    """Cria ~/.config/Claude-<nome> (e copia o setup da conta, se já existir em outro perfil). Devolve a pasta."""
    slug = slugify(name)
    if not slug:
        raise ValueError("Use letras ou números no nome.")
    profile = os.path.join(home, ".config", "Claude-" + slug)
    os.makedirs(profile, mode=0o700, exist_ok=True)
    if account:
        copy_setup(account, profile, home)
    save_profile(os.path.basename(profile), name.strip(), account, home)
    return profile


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


def link_handler():
    """Atalho padrão dos links claude://. Usa o gio quando existe: é ele que abre links no GNOME,
    e o 'xdg-mime query' pode responder pelo cache antigo."""
    cmd = ["gio", "mime", LINK_TYPE] if shutil.which("gio") else ["xdg-mime", "query", "default", LINK_TYPE]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                             env={**os.environ, "LC_ALL": "C"}).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    first = out.splitlines()[0] if out else ""
    return first.rsplit(": ", 1)[-1] if first.endswith(".desktop") else ""


def set_link_handler(name):
    cmd = ["gio", "mime", LINK_TYPE, name] if shutil.which("gio") else ["xdg-mime", "default", name, LINK_TYPE]
    try:
        subprocess.run(cmd, timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def write_login_handler(exe, profile_dir, home=HOME):
    """Atalho invisível que entrega links claude:// ao perfil que está logando."""
    apps = os.path.join(home, ".local", "share", "applications")
    os.makedirs(apps, exist_ok=True)
    # shortcut: aspas sem escape; o perfil vem do slugify, só quebra se HOME tiver aspas ou $. Escapar se aparecer.
    cmd = " ".join(f'"{a}"' for a in exe + ["--user-data-dir=" + profile_dir])
    with open(os.path.join(apps, LOGIN_HANDLER), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Contas Claude (login)\nNoDisplay=true\n"
                f"Exec={cmd} %u\nMimeType={LINK_TYPE};\n")


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
        self.routing = None
        if link_handler() == LOGIN_HANDLER:  # sobrou de uma execução que caiu no meio de um login
            set_link_handler(APP_HANDLER)
        root.title(TITLE)
        root.minsize(480, 0)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Name.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Warn.TLabel", foreground="#a33a00")
        self.body = ttk.Frame(root, padding=16)
        self.body.pack(fill="both", expand=True)
        self.render()

    def close(self):
        self.stop_routing()
        self.root.destroy()

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        if not self.exe:
            ttk.Label(self.body, style="Warn.TLabel", wraplength=440, text=(
                "Claude Desktop não encontrado. Procurei claude-desktop no PATH, em /opt e AppImage "
                "em ~/Applications. Instale o Claude Desktop para usar os botões Desktop.")
            ).pack(fill="x", pady=(0, 12))
        if self.routing:
            ttk.Label(self.body, style="Warn.TLabel", wraplength=440, text=(
                "Login em andamento: o retorno do navegador vai para " + short(self.routing["profile"]) + ".")
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
            ttk.Button(box, text="Criar Desktop", command=lambda: self.add_account(suggestion, row["account"]),
                       state="normal" if self.exe else "disabled").pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Code", command=lambda: self.open_code(row["code"]),
                   state="normal" if row["code"] else "disabled").pack(side="left", padx=(8, 0))

    def open_desktop(self, profile_dir):
        if is_running(profile_dir):
            messagebox.showinfo(TITLE, "O Claude Desktop desta conta já está aberto.", parent=self.root)
            return
        first_login = not logged_account(profile_dir)
        if first_login:
            messagebox.showinfo(TITLE, LOGIN_WARNING, parent=self.root)
        launch(self.exe + ["--user-data-dir=" + profile_dir])
        if first_login:
            self.route_login(profile_dir)

    def route_login(self, profile_dir):
        """Até o login terminar, manda o retorno do navegador (links claude://) só para este perfil."""
        if not (shutil.which("gio") or shutil.which("xdg-mime")):
            return
        self.stop_routing()
        write_login_handler(self.exe, profile_dir)
        current = link_handler()
        self.routing = {"profile": profile_dir, "seen": False, "until": time.time() + 15 * 60,
                        "previous": current if current and current != LOGIN_HANDLER else APP_HANDLER}
        self.render()
        self.keep_routing()

    def keep_routing(self):
        r = self.routing
        if not r:
            return
        running = is_running(r["profile"])
        r["seen"] = r["seen"] or running
        if logged_account(r["profile"]) or time.time() > r["until"] or (r["seen"] and not running):
            self.stop_routing()
            self.render()
            return
        if link_handler() != LOGIN_HANDLER:
            set_link_handler(LOGIN_HANDLER)  # o Claude Desktop se registra de novo como padrão ao abrir
        self.root.after(2000, self.keep_routing)

    def stop_routing(self):
        if self.routing:
            set_link_handler(self.routing["previous"])
            self.routing = None

    def open_code(self, code_dir):
        cmd = terminal_command(code_dir)
        if not cmd:
            messagebox.showerror(TITLE, "Nenhum terminal encontrado (gnome-terminal, ptyxis, konsole...).",
                                 parent=self.root)
            return
        launch(cmd)

    def add_account(self, suggestion="", account=None):
        name = simpledialog.askstring(TITLE, "Nome da nova conta:", initialvalue=suggestion, parent=self.root)
        if not name or not name.strip():
            return
        try:
            profile = create_profile(name, account)
        except ValueError as e:
            messagebox.showerror(TITLE, str(e), parent=self.root)
            return
        self.render()
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
