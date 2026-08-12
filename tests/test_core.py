import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from renpy_translate.core import HOOK_NAME, Store, install_hook, lookup_dictionary, translate, uninstall_hook


class TranslationHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        type(self).calls += 1
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        assert self.headers["Authorization"] == "Bearer test-key"
        assert request["model"] == "test-model"
        assert request["messages"][-1]["content"] == "Hello"
        body = json.dumps({
            "choices": [{"message": {"content": "你好"}}]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


class CoreTest(unittest.TestCase):
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
            options = {
                "text": "Hello",
                "base_url": "http://127.0.0.1:{}".format(server.server_port),
                "model": "test-model",
                "target_language": "zh-CN",
                "api_key": "test-key",
            }
            self.assertEqual(translate(store, **options), ("你好", False))
            self.assertEqual(translate(store, **options), ("你好", True))
            self.assertEqual(TranslationHandler.calls, 1)

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
