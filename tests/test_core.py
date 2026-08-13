import json
import tempfile
import threading
import unittest
import hashlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from renpy_translate.core import HOOK_NAME, Store, install_hook, lookup_dictionary, translate, uninstall_hook, update_status


class TranslationHandler(BaseHTTPRequestHandler):
    calls = 0
    retries = 0

    def do_POST(self):
        type(self).calls += 1
        if self.path.endswith("/retry/chat/completions") and type(self).retries < 1:
            type(self).retries += 1
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        if self.path.endswith("/chat/completions"):
            request = json.loads(raw)
            assert self.headers["Authorization"] == "Bearer test-secret"
            assert request["model"] == "test-model"
            body = {"choices": [{"message": {"content": "你好"}}]}
        elif self.path.endswith("/v2/translate"):
            request = json.loads(raw)
            assert self.headers["Authorization"] == "DeepL-Auth-Key test-secret"
            assert request == {"text": ["Hello"], "target_lang": "ZH-HANS"}
            body = {"translations": [{"text": "你好"}]}
        elif self.path == "/google":
            request = json.loads(raw)
            assert self.headers["X-Goog-Api-Key"] == "test-secret"
            assert request["q"] == "Hello"
            body = {"data": {"translations": [{"translatedText": "你好"}]}}
        else:
            request = {key: value[0] for key, value in urllib.parse.parse_qs(raw.decode()).items()}
            if self.path == "/baidu":
                expected = hashlib.md5((request["appid"] + request["q"] + request["salt"] + "test-secret").encode()).hexdigest()
                assert request["sign"] == expected
                body = {"trans_result": [{"dst": "你好"}]}
            else:
                sign_input = request["q"]
                expected = hashlib.sha256((request["appKey"] + sign_input + request["salt"] + request["curtime"] + "test-secret").encode()).hexdigest()
                assert request["sign"] == expected and request["signType"] == "v3"
                body = {"translation": ["你好"]}
        body = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class CoreTest(unittest.TestCase):
    def test_update_status(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return json.dumps({"tag_name": "v0.2.0", "html_url": "https://example.test/release"}).encode()
        self.assertTrue(update_status("0.1.0", opener=lambda *_args, **_kwargs: Response())["available"])
    def test_dictionary_lookup(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as file:
            import sqlite3
            connection = sqlite3.connect(file.name)
            connection.execute("CREATE TABLE dictionary (word TEXT PRIMARY KEY COLLATE NOCASE, phonetic TEXT, translation TEXT)")
            connection.execute("INSERT INTO dictionary VALUES ('hello', 'həˈləʊ', '你好')")
            connection.commit()
            connection.close()
            self.assertEqual(lookup_dictionary("Hello", file.name)["translation"], "你好")
            self.assertIsNone(lookup_dictionary("missing", file.name))
    def test_install_and_uninstall_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            (game / "scripts.rpa").touch()

            target, created = install_hook(root)
            self.assertTrue(created)
            self.assertEqual(target.name, HOOK_NAME)
            self.assertEqual(install_hook(root), (target, False))

            compiled = target.with_suffix(".rpyc")
            compiled.touch()
            self.assertEqual(uninstall_hook(root), [target, compiled])
            self.assertFalse(target.exists())
            self.assertFalse(compiled.exists())

    def test_refuses_to_overwrite_foreign_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            game.mkdir()
            (game / "script.rpyc").touch()
            (game / HOOK_NAME).write_text("foreign")
            with self.assertRaises(FileExistsError):
                install_hook(game)

    def test_store_and_translation_cache(self):
        TranslationHandler.calls = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), TranslationHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        store = Store(":memory:")
        try:
            base = "http://127.0.0.1:{}".format(server.server_port)
            for provider, path in (("openai", "/openai"), ("deepl", "/deepl"),
                                   ("google", "/google"), ("baidu", "/baidu"),
                                   ("youdao", "/youdao")):
                options = {
                    "text": "Hello", "provider": provider, "base_url": base + path,
                    "model": "test-model", "target_language": "zh-CN",
                    "credential_id": "test-id", "secret": "test-secret",
                }
                self.assertEqual(translate(store, **options), ("你好", False))
                self.assertEqual(translate(store, **options), ("你好", True))
            self.assertEqual(TranslationHandler.calls, 5)

            TranslationHandler.retries = 0
            retry = dict(options, provider="openai", base_url=base + "/retry", text="Retry")
            self.assertEqual(translate(store, **retry), ("你好", False))
            self.assertEqual(TranslationHandler.retries, 1)

            item_id = store.save_item("word", "Hello", "你好", "Hello, world.")
            self.assertEqual(store.saved_items()[0]["id"], item_id)
            self.assertEqual(len(store.saved_items("你好")), 1)
            store.update_saved_item(item_id, "Hello!", "您好")
            self.assertEqual(store.saved_items()[0]["source_text"], "Hello!")
            with tempfile.TemporaryDirectory() as directory:
                export = Path(directory) / "wordbook.csv"
                store.export_saved_items(export)
                self.assertIn("Hello!", export.read_text(encoding="utf-8-sig"))
                with self.assertRaises(FileExistsError):
                    store.export_saved_items(export)
            store.delete_saved_item(item_id)
            self.assertEqual(store.saved_items(), [])
        finally:
            store.close()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
