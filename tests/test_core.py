import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from renpy_translate.core import HOOK_NAME, Store, install_hook, translate, uninstall_hook


class TranslationHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        type(self).calls += 1
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
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
            }
            self.assertEqual(translate(store, **options), ("你好", False))
            self.assertEqual(translate(store, **options), ("你好", True))
            self.assertEqual(TranslationHandler.calls, 1)

            item_id = store.save_item("word", "Hello", "你好", "Hello, world.")
            self.assertEqual(store.saved_items()[0]["id"], item_id)
        finally:
            store.close()
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
