import os
import tempfile
import unittest
from unittest import mock

import launcher
from launcher import write_json


class DetectAccounts(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)  # rodando dentro do Claude Code, ela vazaria para code_accounts

    def test_pairs_by_account_then_suffix(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            write_json(os.path.join(home, ".claude.json"),
                       {"oauthAccount": {"emailAddress": "conta-a", "accountUuid": "u1"}})
            write_json(os.path.join(home, ".claude-work", ".claude.json"),
                       {"oauthAccount": {"emailAddress": "conta-b", "accountUuid": "u2"}})
            write_json(os.path.join(home, ".config", "Claude", "config.json"), {"lastKnownAccountUuid": "u2"})
            os.makedirs(os.path.join(home, ".config", "Claude-novo"))
            write_json(launcher.names_file(home), {"Claude-novo": "Conta Nova"})

            rows = {r["label"]: r for r in launcher.detect_accounts(home)}

            self.assertEqual(rows["conta-b"]["desktop"], os.path.join(home, ".config", "Claude"))
            self.assertEqual(rows["conta-b"]["code"], os.path.join(home, ".claude-work"))
            self.assertEqual(rows["Conta Nova"]["code"], os.path.join(home, ".claude-novo"))
            self.assertIsNone(rows["conta-a"]["desktop"])
            self.assertEqual(rows["conta-a"]["code"], os.path.join(home, ".claude"))
            self.assertEqual(len(rows), 3)

    def test_new_profile_copies_setup_but_never_login(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            write_json(os.path.join(home, ".claude.json"),
                       {"oauthAccount": {"emailAddress": "conta-a", "accountUuid": "u1"}})
            main = os.path.join(home, ".config", "Claude")
            write_json(os.path.join(main, "config.json"), {"lastKnownAccountUuid": "u2", "oauth:tokenCache": "x"})
            write_json(os.path.join(main, "claude-code-sessions", "u1", "org", "local_1.json"), {"cwd": "/p"})
            write_json(os.path.join(main, "claude-code-sessions", "u2", "org", "local_2.json"), {"cwd": "/q"})
            write_json(os.path.join(main, "ssh_configs.json"), {"configs": []})
            write_json(os.path.join(main, "git-worktrees.json"), {"worktrees": {}})
            write_json(os.path.join(main, "claude_desktop_config.json"), {"preferences": {}})
            os.makedirs(os.path.join(main, "git-shadow", "x"))
            write_json(os.path.join(main, "ssh-remote-server-state.json"), {"tokens": {}})
            open(os.path.join(main, "Cookies"), "w").close()
            before = sorted(os.listdir(main))

            profile = launcher.create_profile("Conta A", "u1", home)

            copied = {os.path.relpath(os.path.join(d, f), profile) for d, _, fs in os.walk(profile) for f in fs}
            self.assertEqual(copied, {os.path.join("claude-code-sessions", "u1", "org", "local_1.json")})
            self.assertEqual(sorted(os.listdir(main)), before)
            rows = {r["label"]: r for r in launcher.detect_accounts(home)}
            self.assertEqual(rows["Conta A"]["code"], os.path.join(home, ".claude"))  # pareia antes do login
            self.assertEqual(len(rows), 2)

    def test_oauth_account_that_is_not_a_dict_is_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            write_json(os.path.join(home, ".claude.json"), {"oauthAccount": "quebrado"})
            self.assertEqual(launcher.code_accounts(home)[0]["email"], None)

    def test_slugify(self):
        self.assertEqual(launcher.slugify("  Conta João / 2 "), "Conta-Joao-2")
        self.assertEqual(launcher.slugify("../"), "")

    def test_terminal_sets_the_account_folder(self):
        with mock.patch.object(launcher.shutil, "which", lambda name: "/usr/bin/" + name):
            default = " ".join(launcher.terminal_command(os.path.join(launcher.HOME, ".claude")))
            other = " ".join(launcher.terminal_command(os.path.join(launcher.HOME, ".claude-x")))
        self.assertIn("unset CLAUDE_CONFIG_DIR", default)
        self.assertIn("export CLAUDE_CONFIG_DIR=" + os.path.join(launcher.HOME, ".claude-x"), other)


MIMEAPPS = """[Default Applications]
x-scheme-handler/claude=com.anthropic.Claude.desktop
x-scheme-handler/codex=chatgpt.desktop

[Added Associations]

[Other]
text/plain=gedit.desktop;
"""


class FakeSystem(unittest.TestCase):
    """HOME falso e portal simulado: nada aqui toca o sistema real."""

    def setUp(self):
        self.portal = {"snap.firefox": ["com.anthropic.Claude", "1", "3"]}
        fakes = {
            "link_apps": lambda: ["com.anthropic.Claude.desktop", "outro.desktop"],
            "portal_choices": lambda: dict(self.portal),
            "set_portal_choice": lambda b, c: self.portal.__setitem__(b, c) if c else self.portal.pop(b, None),
        }
        for name, fake in fakes.items():
            patcher = mock.patch.object(launcher, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def mimeapps(self, home, text=None):
        path = launcher.mimeapps_file(home)
        if text is not None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(text)
        with open(path) as f:
            return f.read()


class Links(FakeSystem):
    def test_take_then_restore_leaves_everything_as_it_was(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            handler = os.path.join(launcher.apps_dir(home), launcher.LOGIN_HANDLER)

            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)

            self.assertEqual(launcher.mime_entries(home), {
                "groups": ["Default Applications", "Added Associations", "Other", "Removed Associations"],
                "Default Applications": launcher.LOGIN_HANDLER,
                "Added Associations": launcher.LOGIN_HANDLER + ";",
                "Removed Associations": "com.anthropic.Claude.desktop;outro.desktop;"})
            self.assertIn("x-scheme-handler/codex=chatgpt.desktop", self.mimeapps(home))
            self.assertEqual(self.portal["snap.firefox"], ["contas-claude-login", "3", "3"])
            with open(handler) as f:
                self.assertIn('"--user-data-dir=/p/Claude-x" %u', f.read())

            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)  # 2ª vez guarda o original
            launcher.restore_links(home)

            self.assertEqual(self.mimeapps(home), MIMEAPPS)
            self.assertEqual(self.portal, {"snap.firefox": ["com.anthropic.Claude", "1", "3"]})
            self.assertFalse(os.path.exists(handler))
            self.assertFalse(os.path.exists(launcher.routing_file(home)))

    def test_restore_after_crash_without_state(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            os.remove(launcher.routing_file(home))  # o estado se perdeu

            launcher.restore_links(home)

            self.assertEqual(launcher.mime_entries(home), {
                "groups": ["Default Applications", "Added Associations", "Other", "Removed Associations"],
                "Default Applications": launcher.APP_HANDLER, "Added Associations": None,
                "Removed Associations": "outro.desktop;"})

    def test_autostart_undoes_a_crash_until_restore(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            with open(launcher.restore_entry(home)) as f:
                self.assertIn("launcher.py\" --restore", f.read())
            launcher.restore_links(home)
            self.assertFalse(os.path.exists(launcher.restore_entry(home)))

    def test_user_choices_without_our_trace_are_kept(self):
        own = MIMEAPPS.replace("[Added Associations]\n", "[Added Associations]\n\n[Removed Associations]\n"
                               "x-scheme-handler/claude=com.anthropic.Claude.desktop;\n")
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, own)
            launcher.restore_links(home)
            self.assertEqual(self.mimeapps(home), own)
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            launcher.restore_links(home)
            self.assertEqual(self.mimeapps(home), own)

    def test_duplicate_line_does_not_win_over_ours(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS + "[Default Applications]\nx-scheme-handler/claude=velho.desktop\n")
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            self.assertEqual(launcher.mime_entries(home)["Default Applications"], launcher.LOGIN_HANDLER)
            self.assertEqual(self.mimeapps(home).count("x-scheme-handler/claude="), 3)

    def test_broken_state_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            write_json(launcher.routing_file(home), {"mime": {"Default Applications": "x"}})
            launcher.restore_links(home)
            self.assertEqual(self.mimeapps(home), MIMEAPPS)
            self.assertFalse(os.path.exists(launcher.routing_file(home)))

    def test_odd_bytes_symlink_and_mode_survive(self):
        with tempfile.TemporaryDirectory() as home:
            real = os.path.join(home, "dotfiles", "mimeapps.list")
            os.makedirs(os.path.dirname(real))
            with open(real, "wb") as f:
                f.write(MIMEAPPS.encode() + b"[Other]\nx=caf\xe9\n")
            os.chmod(real, 0o600)
            os.makedirs(os.path.join(home, ".config"))
            os.symlink(real, launcher.mimeapps_file(home))
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            launcher.restore_links(home)
            self.assertTrue(os.path.islink(launcher.mimeapps_file(home)))
            self.assertEqual(os.stat(real).st_mode & 0o777, 0o600)
            with open(real, "rb") as f:
                self.assertEqual(f.read(), MIMEAPPS.encode() + b"[Other]\nx=caf\xe9\n")

    def test_portal_choice_made_during_login_is_cleaned(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            self.portal.clear()
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            self.portal["snap.outro"] = ["contas-claude-login", "1", "3"]  # o usuário escolheu na janela
            launcher.restore_links(home)
            self.assertEqual(self.portal, {})

    def test_restore_without_routing_does_not_touch_the_file(self):
        with tempfile.TemporaryDirectory() as home:
            self.mimeapps(home, MIMEAPPS)
            before = os.stat(launcher.mimeapps_file(home)).st_mtime_ns
            launcher.restore_links(home)
            self.assertEqual(os.stat(launcher.mimeapps_file(home)).st_mtime_ns, before)


class KeepRouting(FakeSystem):
    """O ciclo de 2 s do App, sem Tk: reaplica o roteamento e para quando o login acontece."""

    def app(self, home, profile):
        app = launcher.App.__new__(launcher.App)
        app.home, app.exe, app.root = home, ["/usr/bin/claude-desktop"], mock.Mock()
        app.render = mock.Mock()
        app.routing = {"profile": profile, "seen": False, "until": launcher.time.time() + 60,
                       "mime": launcher.take_links(app.exe, profile, home)}
        return app

    def test_reapplies_after_desktop_registers_and_stops_on_login(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(launcher, "is_running", lambda p: True), \
                mock.patch.object(launcher, "messagebox", mock.Mock(), create=True) as box:
            self.mimeapps(home, MIMEAPPS)
            profile = os.path.join(home, ".config", "Claude-x")
            launcher.save_profile("Claude-x", "x", "u-certa", home)
            app = self.app(home, profile)
            launcher.set_mime_entries({"groups": None, "Default Applications": "com.anthropic.Claude.desktop",
                                       "Added Associations": None, "Removed Associations": None}, home)

            app.keep_routing()
            self.assertEqual(launcher.mime_entries(home)["Default Applications"], launcher.LOGIN_HANDLER)
            app.root.after.assert_called_once()

            write_json(os.path.join(profile, "config.json"), {"lastKnownAccountUuid": "u-errada"})
            app.keep_routing()
            self.assertIsNone(app.routing)
            self.assertEqual(self.mimeapps(home), MIMEAPPS)
            box.showwarning.assert_called_once()


class Lock(unittest.TestCase):
    def test_only_one_launcher(self):
        with tempfile.TemporaryDirectory() as home:
            first = launcher.take_lock(home)
            self.assertIsNotNone(first)
            self.assertIsNone(launcher.take_lock(home))
            first.close()
            again = launcher.take_lock(home)
            self.assertIsNotNone(again)
            again.close()


class Launch(unittest.TestCase):
    def test_does_not_pass_the_claude_session_on(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ACCOUNT_UUID": "u", "ANTHROPIC_BASE_URL": "x", "KEEP": "1"}), \
                mock.patch.object(launcher.subprocess, "Popen") as popen:
            launcher.launch(["true"])
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["KEEP"], "1")
        self.assertFalse([k for k in env if k.startswith(("CLAUDE", "ANTHROPIC"))])


if __name__ == "__main__":
    unittest.main()
