import hashlib
import json
import os
import socket
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


HOST = "127.0.0.1"
PORT = 19840
MAX_PACKET = 65_507
HOOK_NAME = "renpy_translate_hook.rpy"
HOOK_PATH = Path(__file__).parent.parent / "renpy_hook" / HOOK_NAME


def parse_packet(data):
    if len(data) > MAX_PACKET:
        raise ValueError("UDP packet is too large")

    event = json.loads(data.decode("utf-8"))
    if not isinstance(event, dict):
        raise ValueError("packet must contain a JSON object")
    if event.get("protocol") != 1:
        raise ValueError("unsupported protocol")
    if event.get("event") not in ("dialogue", "choice"):
        raise ValueError("unsupported event")

    for field in ("text", "who", "game", "game_version"):
        value = event.get(field, "")
        if not isinstance(value, str):
            raise ValueError("{} must be a string".format(field))
    if not event["text"].strip():
        raise ValueError("text must be a non-empty string")
    return event


def receive_once(sock):
    data, _address = sock.recvfrom(MAX_PACKET + 1)
    return parse_packet(data)


def _game_directory(path):
    path = Path(path).expanduser().resolve()
    game = path if path.name == "game" else path / "game"
    if not game.is_dir():
        raise ValueError("not a Ren'Py game directory: {}".format(path))
    if not any(game.glob("*.rpa")) and not any(game.glob("*.rpyc")):
        raise ValueError("no Ren'Py scripts or archives found in {}".format(game))
    return game


def install_hook(path):
    game = _game_directory(path)
    target = game / HOOK_NAME
    compiled = target.with_suffix(".rpyc")
    source = HOOK_PATH.read_bytes()

    if target.exists():
        if target.read_bytes() == source:
            return target, False
        raise FileExistsError("refusing to overwrite {}".format(target))
    if compiled.exists():
        raise FileExistsError("refusing to replace orphan {}".format(compiled))

    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(source)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target, True


def uninstall_hook(path):
    game = _game_directory(path)
    target = game / HOOK_NAME
    compiled = target.with_suffix(".rpyc")

    if not target.exists():
        if compiled.exists():
            raise FileExistsError("refusing to remove orphan {}".format(compiled))
        return []
    if target.read_bytes() != HOOK_PATH.read_bytes():
        raise FileExistsError("refusing to remove modified {}".format(target))

    removed = []
    for file in (target, compiled):
        if file.exists():
            file.unlink()
            removed.append(file)
    return removed


class Store:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                game TEXT NOT NULL,
                game_version TEXT NOT NULL,
                who TEXT NOT NULL,
                text TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS translations (
                cache_key TEXT PRIMARY KEY,
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saved_items (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL CHECK (kind IN ('word', 'sentence')),
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                context TEXT NOT NULL,
                game TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def close(self):
        self.connection.close()

    def add_event(self, event):
        with self.connection:
            self.connection.execute(
                """INSERT INTO events
                   (event, game, game_version, who, text, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event["event"],
                    event.get("game", ""),
                    event.get("game_version", ""),
                    event.get("who", ""),
                    event["text"],
                    _now(),
                ),
            )

    def cached_translation(self, cache_key):
        row = self.connection.execute(
            "SELECT translated_text FROM translations WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        return row[0] if row else None

    def cache_translation(self, cache_key, request, translated_text):
        with self.connection:
            self.connection.execute(
                """INSERT OR REPLACE INTO translations
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cache_key,
                    request["text"],
                    translated_text,
                    request["base_url"],
                    request["model"],
                    request["source_language"],
                    request["target_language"],
                    _now(),
                ),
            )

    def save_item(self, kind, source_text, translated_text, context="", game=""):
        if kind not in ("word", "sentence"):
            raise ValueError("kind must be word or sentence")
        if not source_text.strip() or not translated_text.strip():
            raise ValueError("source and translation must not be empty")
        with self.connection:
            cursor = self.connection.execute(
                """INSERT INTO saved_items
                   (kind, source_text, translated_text, context, game, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (kind, source_text, translated_text, context, game, _now()),
            )
        return cursor.lastrowid

    def saved_items(self):
        return self.connection.execute(
            "SELECT * FROM saved_items ORDER BY id DESC"
        ).fetchall()


def translate(store, *, text, base_url, model, target_language,
              source_language="auto", api_key="", opener=None):
    if not text.strip():
        raise ValueError("text must not be empty")
    request_data = {
        "text": text,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "source_language": source_language,
        "target_language": target_language,
    }
    cache_key = hashlib.sha256(
        json.dumps(request_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    cached = store.cached_translation(cache_key)
    if cached is not None:
        return cached, True

    prompt = "Translate from {} to {}. Return only the translation.".format(
        source_language, target_language
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer {}".format(api_key)
    endpoint = request_data["base_url"]
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"

    http_request = urllib.request.Request(endpoint, body, headers, method="POST")
    open_request = opener or urllib.request.urlopen
    with open_request(http_request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    try:
        translated = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ValueError("invalid translation response") from error
    if not translated:
        raise ValueError("translation response is empty")

    store.cache_translation(cache_key, request_data, translated)
    return translated, False


def _now():
    return datetime.now(timezone.utc).isoformat()
