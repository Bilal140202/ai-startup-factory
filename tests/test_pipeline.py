import importlib
import os
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AGENTS_DIR = os.path.join(ROOT, "agents")

if AGENTS_DIR not in sys.path:
    sys.path.insert(0, AGENTS_DIR)


def load_module(module_name, env=None):
    env = env or {}
    previous = {}
    for key, value in env.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        if module_name in sys.modules:
            return importlib.reload(sys.modules[module_name])
        return importlib.import_module(module_name)
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


class SharedTests(unittest.TestCase):
    def test_extract_json_handles_fenced_payload(self):
        shared = load_module("shared")
        payload = '```json\n{"ok": true, "count": 2}\n```'
        parsed = shared.extract_json(payload)
        self.assertEqual(parsed["count"], 2)


class LiamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(
            "liam.scout",
            {
                "GITHUB_TOKEN": "test-token",
                "GITHUB_USERNAME": "test-user",
            },
        )

    def test_build_candidate_keeps_high_signal_problem(self):
        idea = self.module.build_candidate(
            "Need a tool for invoice follow-ups",
            "I run a small agency and keep doing invoice follow ups manually. "
            "Would pay for a tool that automates reminder emails and tracks replies.",
            "https://example.com",
            12,
            "Entrepreneur",
            "reddit-post",
        )
        self.assertIsNotNone(idea)
        self.assertGreaterEqual(idea["signal_score"], 4)

    def test_build_candidate_rejects_promo_noise(self):
        idea = self.module.build_candidate(
            "I built my startup in a weekend",
            "Just shipped my open source launch. Subscribe to my newsletter for more updates.",
            "https://example.com",
            40,
            "SideProject",
            "reddit-post",
        )
        self.assertIsNone(idea)


class KyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(
            "kyle.builder",
            {
                "GITHUB_TOKEN": "test-token",
                "GITHUB_USERNAME": "test-user",
                "NETLIFY_AUTH_TOKEN": "netlify-token",
            },
        )

    def test_repo_full_name_falls_back_to_repo_url(self):
        full_name = self.module.repo_full_name({"repo_url": "https://github.com/openai/example"})
        self.assertEqual(full_name, "openai/example")

    def test_validate_generated_output_for_html_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
                f.write("<html><body><input><script>console.log('ok')</script></body></html>")
            self.module.validate_generated_output("html-tool", tmp)

    def test_validate_generated_output_for_python_webapp(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "templates"), exist_ok=True)
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as f:
                f.write("from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef home():\n    return 'ok'\n")
            with open(os.path.join(tmp, "templates", "index.html"), "w", encoding="utf-8") as f:
                f.write("<html><body><form><input></form></body></html>")
            with open(os.path.join(tmp, "requirements.txt"), "w", encoding="utf-8") as f:
                f.write("flask\ngunicorn\n")
            self.module.validate_generated_output("python-webapp", tmp)


class NickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(
            "nick.marketer",
            {
                "GITHUB_USERNAME": "test-user",
            },
        )

    def test_validate_content_accepts_reasonable_payload(self):
        payload = {
            "blog_post": "x" * 250,
            "tweet_thread": "short thread but long enough " * 3,
            "linkedin": "professional launch update " * 6,
            "netlify_url": "https://example.netlify.app",
        }
        self.module.validate_content(payload)


class VeraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module(
            "vera.gatekeeper",
            {
                "DISCORD_BOT_TOKEN": "discord-token",
                "DISCORD_APPROVAL_CHANNEL_ID": "123",
                "DISCORD_OWNER_USER_ID": "999",
            },
        )

    def test_is_valid_approval_requires_owner_and_exact_content(self):
        message = {
            "author": {"id": "999"},
            "content": "approve",
            "message_reference": {"message_id": "42"},
        }
        self.assertTrue(self.module.is_valid_approval(message, "42"))
        self.assertFalse(self.module.is_valid_approval({"author": {"id": "111"}, "content": "approve"}, "42"))
        self.assertFalse(self.module.is_valid_approval({"author": {"id": "999"}, "content": "approve now"}, "42"))


if __name__ == "__main__":
    unittest.main()
