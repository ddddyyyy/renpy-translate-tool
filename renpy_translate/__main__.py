import argparse
import json
import os
import socket
from pathlib import Path

from .core import HOST, PORT, Store, install_hook, receive_once, translate, uninstall_hook


DEFAULT_DB = Path.home() / ".renpy-translate-tool.sqlite3"


def main():
    parser = argparse.ArgumentParser(prog="renpy-translate")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install")
    install.add_argument("game")
    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("game")

    listen = commands.add_parser("listen")
    listen.add_argument("--port", type=int, default=PORT)
    listen.add_argument("--once", action="store_true")

    run_translate = commands.add_parser("translate")
    run_translate.add_argument("text")
    run_translate.add_argument("--base-url", required=True)
    run_translate.add_argument("--model", required=True)
    run_translate.add_argument("--source", default="auto")
    run_translate.add_argument("--target", default="zh-CN")
    run_translate.add_argument("--api-key-env", default="OPENAI_API_KEY")

    save = commands.add_parser("save")
    save.add_argument("kind", choices=("word", "sentence"))
    save.add_argument("source")
    save.add_argument("translation")
    save.add_argument("--context", default="")
    save.add_argument("--game", default="")
    commands.add_parser("saved")
    args = parser.parse_args()

    if args.command == "install":
        path, created = install_hook(args.game)
        print(("Installed " if created else "Already installed ") + str(path))
        return
    if args.command == "uninstall":
        removed = uninstall_hook(args.game)
        print("Removed " + ", ".join(map(str, removed)) if removed else "Not installed")
        return

    store = Store(args.db)
    try:
        if args.command == "listen":
            listen_for_events(store, args.port, args.once)
        elif args.command == "translate":
            result, cached = translate(
                store,
                text=args.text,
                base_url=args.base_url,
                model=args.model,
                source_language=args.source,
                target_language=args.target,
                api_key=os.environ.get(args.api_key_env, ""),
            )
            print(result + (" [cached]" if cached else ""))
        elif args.command == "save":
            print(store.save_item(
                args.kind, args.source, args.translation, args.context, args.game
            ))
        elif args.command == "saved":
            for item in store.saved_items():
                print(json.dumps(dict(item), ensure_ascii=False))
    finally:
        store.close()


def listen_for_events(store, port, once=False):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((HOST, port))
        print("Listening on {}:{}".format(HOST, port), flush=True)
        while True:
            try:
                event = receive_once(sock)
            except KeyboardInterrupt:
                return
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                print("Ignored packet: {}".format(error), flush=True)
                continue
            store.add_event(event)
            print(json.dumps(event, ensure_ascii=False), flush=True)
            if once:
                return


if __name__ == "__main__":
    main()
