import json
import os
import tempfile
import unittest
from unittest import mock

import launcher


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


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

    def test_default_code_dir_unsets_env(self):
        cmd = launcher.terminal_command(os.path.join(launcher.HOME, ".claude"))
        if cmd is None:
            self.skipTest("nenhum terminal instalado")
        self.assertIn("unset CLAUDE_CONFIG_DIR", " ".join(cmd))


class Links(unittest.TestCase):
    """Roteamento dos links claude:// com o sistema simulado: nada aqui toca o MIME nem o portal reais."""

    def setUp(self):
        self.mime = ["com.anthropic.Claude.desktop"]
        self.portal = {"snap.firefox": ["com.anthropic.Claude", "1", "3"]}
        fakes = {
            "link_handler": lambda: self.mime[-1],
            "set_link_handler": self.mime.append,
            "portal_choices": lambda: dict(self.portal),
            "set_portal_choice": lambda b, c: self.portal.__setitem__(b, c) if c else self.portal.pop(b, None),
        }
        for name, fake in fakes.items():
            patcher = mock.patch.object(launcher, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_take_then_restore(self):
        with tempfile.TemporaryDirectory() as home:
            handler = os.path.join(launcher.apps_dir(home), launcher.LOGIN_HANDLER)
            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)
            self.assertEqual(self.mime[-1], launcher.LOGIN_HANDLER)
            self.assertEqual(self.portal["snap.firefox"], ["contas-claude-login", "3", "3"])
            with open(handler) as f:
                self.assertIn('"--user-data-dir=/p/Claude-x" %u', f.read())

            launcher.take_links(["/usr/bin/claude-desktop"], "/p/Claude-x", home)  # 2ª vez guarda o original
            launcher.restore_links(home)

            self.assertEqual(self.mime[-1], "com.anthropic.Claude.desktop")
            self.assertEqual(self.portal, {"snap.firefox": ["com.anthropic.Claude", "1", "3"]})
            self.assertFalse(os.path.exists(handler))
            self.assertFalse(os.path.exists(launcher.routing_file(home)))

    def test_restore_after_crash_without_state(self):
        with tempfile.TemporaryDirectory() as home:
            self.mime.append(launcher.LOGIN_HANDLER)
            launcher.restore_links(home)
            self.assertEqual(self.mime[-1], launcher.APP_HANDLER)


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
