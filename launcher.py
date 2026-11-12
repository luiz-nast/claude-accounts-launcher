#!/usr/bin/env python3
"""Contas Claude: abre várias contas do Claude Desktop e do Claude Code ao mesmo tempo."""
import fcntl
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata

HOME = os.path.expanduser("~")
TITLE = "Contas Claude"
LOGIN_WARNING = ("Entre só com \"Continuar com Google\" e escolha a conta certa no navegador. "
                 "Não use login por e-mail: esse link pode cair na janela de outra conta e trocar a conta dela.\n\n"
                 "Deixe o Contas Claude aberto até terminar o login. Enquanto isso, o retorno do navegador "
                 "vai só para esta janela nova.")
WRONG_ACCOUNT = ("A janela nova entrou numa conta diferente da esperada. Saia da conta nela "
                 "e entre de novo com a conta certa.")
LINK_TYPE = "x-scheme-handler/claude"
LOGIN_HANDLER = "contas-claude-login.desktop"
LOGIN_ID = LOGIN_HANDLER.removesuffix(".desktop")
RESTORE_ENTRY = "contas-claude-restore.desktop"
APP_HANDLER = "com.anthropic.Claude.desktop"
# Setup que vai para um perfil novo: só as sessões da própria conta. Login (Cookies, config.json, Local Storage,
# tokens) nunca é copiado. git-worktrees.json e git-shadow também não: o Desktop do perfil novo trataria as
# worktrees do outro perfil como órfãs e poderia removê-las. As pastas temporárias das sessões ficam onde estão.
ACCOUNT_DIRS = ("claude-code-sessions", "local-agent-mode-sessions")
SHARED_SETUP = (os.path.join("local-agent-mode-sessions", "skills-plugin"),)
MIME_GROUPS = ("Default Applications", "Added Associations", "Removed Associations")
PORTAL = ["busctl", "--user", "--json=short", "call", "org.freedesktop.impl.portal.PermissionStore",
          "/org/freedesktop/impl/portal/PermissionStore", "org.freedesktop.impl.portal.PermissionStore"]


def names_file(home=HOME):
    return os.path.join(home, ".config", "claude-accounts", "accounts.json")


def routing_file(home=HOME):
    return os.path.join(home, ".config", "claude-accounts", "routing.json")


def take_lock(home=HOME):
    """Só um Contas Claude por vez: um segundo desfaria o login em andamento do primeiro.
    Devolve o arquivo travado (a trava some sozinha quando o processo termina), ou None."""
    path = os.path.join(home, ".config", "claude-accounts", "launcher.lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = open(path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


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


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_profile(base, name, account=None, home=HOME):
    data = read_json(names_file(home))
    data[base] = {"name": name, "account": account} if account else {"name": name}
    write_json(names_file(home), data)


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
        acc = read_json(cfg).get("oauthAccount")
        acc = acc if isinstance(acc, dict) else {}
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
    """Copia para dest as sessões desta conta (ACCOUNT_DIRS/<conta>) e o skills-plugin, vindos de outro perfil
    do Desktop. Só copia o que ainda não existe em dest; a origem não é alterada. Devolve a pasta de origem ou None."""
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
    # Aberto de dentro de uma sessão do Claude, o launcher herdaria a conta dela: não repassa essas variáveis.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    subprocess.Popen(cmd, start_new_session=True, cwd=HOME, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run(cmd):
    """Saída do comando, ou "" se ele não existir ou falhar."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                              env={**os.environ, "LC_ALL": "C"}).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def mimeapps_file(home=HOME):
    return os.path.join(home, ".config", "mimeapps.list")


def read_lines(path):
    # surrogateescape: um byte que não é UTF-8 passa intacto em vez de derrubar o launcher
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            return f.read().splitlines()
    except OSError:
        return []


def mime_entries(home=HOME):
    """Linhas de claude:// no mimeapps.list do usuário: {grupo: valor, ou None se não há linha}.
    A chave "groups" lista os grupos que o arquivo já tem, para a restauração não deixar sobras."""
    entries, group = dict.fromkeys(MIME_GROUPS), None
    entries["groups"] = []
    for line in read_lines(mimeapps_file(home)):
        line = line.strip()
        if line.startswith("["):
            group = line.strip("[]")
            entries["groups"].append(group)
        elif group in MIME_GROUPS and line.startswith(LINK_TYPE + "="):
            entries[group] = line.split("=", 1)[1]  # repetida: vale a última, como no GLib
    return entries


def claude_lines(entries):
    return {g: entries[g] for g in MIME_GROUPS}


def set_mime_entries(entries, home=HOME):
    """Grava estas linhas de claude:// (None apaga a linha) sem mexer no resto do mimeapps.list.
    Um grupo que ficou vazio e não está em entries["groups"] sai inteiro."""
    path = os.path.realpath(mimeapps_file(home))  # se for symlink, grava no destino
    keep = entries.get("groups")
    out, group, pending = [], None, claude_lines(entries)

    def close(g):  # linha que faltou no grupo g entra no fim dele, antes das linhas em branco
        value = pending.pop(g, None)
        if value is not None:
            i = len(out)
            while i and not out[i - 1].strip():
                i -= 1
            out.insert(i, f"{LINK_TYPE}={value}")

    for line in read_lines(path):
        text = line.strip()
        if text.startswith("["):
            close(group)
            group = text.strip("[]")
        elif group in MIME_GROUPS and text.startswith(LINK_TYPE + "="):
            if group in pending:
                value = pending.pop(group)
                if value is not None:
                    out.append(f"{LINK_TYPE}={value}")
            continue  # linha repetida sai: senão a de baixo valeria no lugar da nossa
        out.append(line)
    close(group)
    for g, value in pending.items():
        if value is not None:
            out += ["", f"[{g}]", f"{LINK_TYPE}={value}"]
    for g in MIME_GROUPS:
        header = f"[{g}]"
        if keep is None or g in keep or header not in out:
            continue
        i = out.index(header)
        end = next((k for k in range(i + 1, len(out)) if out[k].startswith("[")), len(out))
        if not any(line.strip() for line in out[i + 1:end]):
            del out[i - 1 if i and not out[i - 1].strip() else i:end]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".contas-claude"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("\n".join(out) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def without_us(entries):
    """As linhas sem o que um roteamento interrompido deixou para trás. Sem rastro nosso, ficam como estão."""
    if not any(LOGIN_HANDLER in (entries[g] or "") for g in MIME_GROUPS[:2]):
        return entries

    def drop(value, *names):
        items = [a for a in (value or "").split(";") if a and a not in names]
        return ";".join(items) + ";" if items else None
    default = entries["Default Applications"]
    return {"groups": entries.get("groups"),
            "Default Applications": APP_HANDLER if default == LOGIN_HANDLER else default,
            "Added Associations": drop(entries["Added Associations"], LOGIN_HANDLER),
            "Removed Associations": drop(entries["Removed Associations"], LOGIN_HANDLER, APP_HANDLER)}


def link_apps():
    """Apps que o sistema conhece para claude:// (o gio lista os registrados com um tab na frente)."""
    out = run(["gio", "mime", LINK_TYPE])
    return list(dict.fromkeys([APP_HANDLER] + [l.strip() for l in out.splitlines() if l.startswith("\t")]))


def portal_choices():
    """Escolha que o portal do sistema (usado por navegadores snap/flatpak) guarda para claude://:
    {navegador: [app, vezes, limite]}. Onde ela vale, o portal abre esse app mesmo havendo um só registrado."""
    try:
        data = json.loads(run(PORTAL + ["Lookup", "ss", "desktop-used-apps", LINK_TYPE]))["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def set_portal_choice(browser, choice):
    if choice:
        run(PORTAL + ["SetPermission", "sbssas", "desktop-used-apps", "true", LINK_TYPE, browser,
                      str(len(choice))] + choice)
    else:
        run(PORTAL + ["DeletePermission", "sss", "desktop-used-apps", LINK_TYPE, browser])


def apps_dir(home=HOME):
    return os.path.join(home, ".local", "share", "applications")


def restore_entry(home=HOME):
    return os.path.join(home, ".config", "autostart", RESTORE_ENTRY)


def write_login_handler(exe, profile_dir, home=HOME):
    """Atalho que entrega links claude:// ao perfil que está logando. Existe só enquanto o login roteia."""
    os.makedirs(apps_dir(home), exist_ok=True)
    # shortcut: aspas sem escape; o perfil vem do slugify, só quebra se HOME tiver aspas ou $. Escapar se aparecer.
    cmd = " ".join(f'"{a}"' for a in exe + ["--user-data-dir=" + profile_dir])
    with open(os.path.join(apps_dir(home), LOGIN_HANDLER), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Contas Claude (login)\n"
                f"Exec={cmd} %u\nMimeType={LINK_TYPE};\n")


def routing_state(home=HOME):
    """routing.json, ou {} se não existir ou estiver incompleto."""
    state = read_json(routing_file(home))
    mime = state.get("mime")
    ok = isinstance(mime, dict) and all(g in mime for g in MIME_GROUPS) and isinstance(state.get("portal", {}), dict)
    return state if ok else {}


def take_links(exe, profile_dir, home=HOME):
    """Manda os links claude:// só para profile_dir e devolve as linhas do mimeapps.list que fazem isso.
    O estado anterior vai para o disco antes de qualquer mudança, e um autostart desfaz tudo no próximo login
    do computador se o launcher cair no meio. O atalho de login vira o único app de claude://: assim o portal
    dos navegadores snap/flatpak (que no Ubuntu sempre perguntaria) abre direto, sem a janela 'Abrir com'."""
    state = routing_state(home)
    if not state:  # se já existe, é o original de um roteamento que não terminou: mantém
        state = {"mime": without_us(mime_entries(home)),
                 "portal": {b: (None if c and c[0] == LOGIN_ID else c) for b, c in portal_choices().items()}}
        write_json(routing_file(home), state)
    os.makedirs(os.path.dirname(restore_entry(home)), exist_ok=True)
    with open(restore_entry(home), "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\nType=Application\nName=Contas Claude (restaurar links)\nNoDisplay=true\n"
                f'Exec="{sys.executable}" "{os.path.abspath(__file__)}" --restore\n')
    write_login_handler(exe, profile_dir, home)
    hidden = [a for a in (state["mime"]["Removed Associations"] or "").split(";") if a]
    hidden += [a for a in link_apps() if a != LOGIN_HANDLER and a not in hidden]
    takeover = {"groups": None, "Default Applications": LOGIN_HANDLER, "Added Associations": LOGIN_HANDLER + ";",
                "Removed Associations": ";".join(hidden) + ";"}
    set_mime_entries(takeover, home)
    for browser in state["portal"]:
        set_portal_choice(browser, [LOGIN_ID, "3", "3"])  # onde o portal lembra a escolha, ela passa a ser a nossa
    return takeover


def restore_links(home=HOME):
    """Devolve os links claude:// para quem tinha antes e apaga o atalho de login. Sem roteamento, não mexe em nada."""
    state = routing_state(home)
    now = mime_entries(home)
    before = state.get("mime") or without_us(now)
    if claude_lines(before) != claude_lines(now) or set(now["groups"]) - set(before.get("groups") or now["groups"]):
        set_mime_entries(before, home)
    saved = state.get("portal") or {}
    for browser, choice in saved.items():
        set_portal_choice(browser, choice)
    for browser, choice in portal_choices().items():  # escolha nossa que o portal gravou durante o login
        if browser not in saved and choice and choice[0] == LOGIN_ID:
            set_portal_choice(browser, None)
    for path in (os.path.join(apps_dir(home), LOGIN_HANDLER), restore_entry(home), routing_file(home)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


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
    def __init__(self, root, home=HOME):
        self.root = root
        self.home = home
        self.exe = find_desktop_exe()
        self.routing = None
        restore_links(home)  # sobra de uma execução que caiu no meio de um login
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
        try:
            self.stop_routing()
        finally:
            self.root.destroy()

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        if not self.exe:
            ttk.Label(self.body, style="Warn.TLabel", wraplength=440, text=(
                "Claude Desktop não encontrado. Procurei claude-desktop no PATH e em /opt, e AppImage "
                "em ~/Applications e ~/.local/bin. Instale o Claude Desktop para usar os botões Desktop.")
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
        first_login = not logged_account(profile_dir)
        running = is_running(profile_dir)
        if running and not first_login:
            messagebox.showinfo(TITLE, "O Claude Desktop desta conta já está aberto.", parent=self.root)
            return
        if first_login:
            # antes de abrir, para o retorno não cair em outra janela; se ela já está aberta com o login
            # pela metade, volta a mandar o retorno do navegador para ela
            messagebox.showinfo(TITLE, LOGIN_WARNING, parent=self.root)
            self.route_login(profile_dir)
        if not running:
            launch(self.exe + ["--user-data-dir=" + profile_dir])

    def route_login(self, profile_dir):
        """Até o login terminar, manda o retorno do navegador (links claude://) só para este perfil."""
        self.stop_routing()
        self.routing = {"profile": profile_dir, "seen": False, "until": time.time() + 15 * 60,
                        "mime": take_links(self.exe, profile_dir, self.home)}
        self.render()
        self.keep_routing()

    def keep_routing(self):
        r = self.routing
        if not r:
            return
        running = is_running(r["profile"])
        r["seen"] = r["seen"] or running
        got = logged_account(r["profile"])
        if got or time.time() > r["until"] or (r["seen"] and not running):
            self.stop_routing()
            self.render()
            want = saved_profiles(self.home).get(os.path.basename(r["profile"]), {}).get("account")
            if got and want and got != want:
                messagebox.showwarning(TITLE, WRONG_ACCOUNT, parent=self.root)
            return
        if claude_lines(mime_entries(self.home)) != claude_lines(r["mime"]):
            set_mime_entries(r["mime"], self.home)  # o Claude Desktop se registra de novo como padrão ao abrir
        self.root.after(2000, self.keep_routing)

    def stop_routing(self):
        if self.routing:
            restore_links(self.home)
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
    lock = take_lock()
    if sys.argv[1:] == ["--restore"]:  # autostart depois de uma queda no meio de um login
        if lock:
            restore_links()
        raise SystemExit
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk
    except ImportError:
        raise SystemExit("Falta o Tkinter. Instale com: sudo apt install python3-tk")
    # O Tk muda a caixa do className; fixar argv0 deixa WM_CLASS igual ao StartupWMClass do .desktop.
    root = tk.Tk(className=TITLE, useTk=False)
    root.tk.setvar("argv0", TITLE)
    root.loadtk()
    if not lock:
        root.withdraw()
        messagebox.showinfo(TITLE, "O Contas Claude já está aberto.")
        raise SystemExit
    App(root)
    root.mainloop()
