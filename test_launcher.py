import json
import os
import tempfile
import unittest

import launcher


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class DetectAccounts(unittest.TestCase):
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
            write_json(os.path.join(main, "ssh-remote-server-state.json"), {"tokens": {}})
            open(os.path.join(main, "Cookies"), "w").close()
            before = sorted(os.listdir(main))

            profile = launcher.create_profile("Conta A", "u1", home)

            copied = {os.path.relpath(os.path.join(d, f), profile) for d, _, fs in os.walk(profile) for f in fs}
            self.assertEqual(copied, {os.path.join("claude-code-sessions", "u1", "org", "local_1.json"),
                                      "ssh_configs.json"})
            self.assertEqual(sorted(os.listdir(main)), before)
            rows = {r["label"]: r for r in launcher.detect_accounts(home)}
            self.assertEqual(rows["Conta A"]["code"], os.path.join(home, ".claude"))  # pareia antes do login
            self.assertEqual(len(rows), 2)

    def test_slugify(self):
        self.assertEqual(launcher.slugify("  Conta João / 2 "), "Conta-Joao-2")
        self.assertEqual(launcher.slugify("../"), "")

    def test_default_code_dir_unsets_env(self):
        cmd = launcher.terminal_command(os.path.join(launcher.HOME, ".claude"))
        if cmd is None:
            self.skipTest("nenhum terminal instalado")
        self.assertIn("unset CLAUDE_CONFIG_DIR", " ".join(cmd))


if __name__ == "__main__":
    unittest.main()
