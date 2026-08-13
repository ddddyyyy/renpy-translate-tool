import argparse
import json
import os
import socket
from pathlib import Path

from .core import HOST, PORT, Store, install_hook, lookup_dictionary, receive_once, translate, uninstall_hook, update_status


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
    run_translate.add_argument("--provider", default="openai")
    run_translate.add_argument("--base-url", required=True)
    run_translate.add_argument("--model", default="")
    run_translate.add_argument("--source", default="auto")
    run_translate.add_argument("--target", default="zh-CN")
    run_translate.add_argument("--credential-id-env", default="TRANSLATION_CREDENTIAL_ID")
    run_translate.add_argument("--secret-env", default="TRANSLATION_SECRET")

    save = commands.add_parser("save")
    save.add_argument("kind", choices=("word", "sentence"))
    save.add_argument("source")
    save.add_argument("translation")
    save.add_argument("--context", default="")
    save.add_argument("--game", default="")
    save.add_argument("--tags", default="")
    save.add_argument("--group", default="")
    commands.add_parser("saved")
    saved = commands.choices["saved"]
    saved.add_argument("--query", default="")
    saved.add_argument("--group", default="")
    update = commands.add_parser("update-saved")
    update.add_argument("id", type=int)
    update.add_argument("source")
    update.add_argument("translation")
    update.add_argument("--tags", default="")
    update.add_argument("--group", default="")
    delete = commands.add_parser("delete-saved")
    delete.add_argument("id", type=int)
    export = commands.add_parser("export-saved")
    export.add_argument("path")
    import_saved = commands.add_parser("import-saved")
    import_saved.add_argument("path")
    commands.add_parser("due-saved")
    review = commands.add_parser("review-saved")
    review.add_argument("id", type=int)
    review.add_argument("rating", choices=("again", "hard", "good", "easy"))
    sync = commands.add_parser("sync-saved")
    sync.add_argument("directory")
    lookup = commands.add_parser("lookup")
    lookup.add_argument("word")
    check_update = commands.add_parser("check-update")
    check_update.add_argument("version")
    args = parser.parse_args()

    if args.command == "install":
        path, created = install_hook(args.game)
        print(("Installed " if created else "Already installed ") + str(path))
        return
    if args.command == "uninstall":
        removed = uninstall_hook(args.game)
        print("Removed " + ", ".join(map(str, removed)) if removed else "Not installed")
        return

    if args.command == "lookup":
        print(json.dumps(lookup_dictionary(args.word), ensure_ascii=False))
        return
    if args.command == "check-update":
        print(json.dumps(update_status(args.version), ensure_ascii=False))
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
                provider=args.provider,
                source_language=args.source,
                target_language=args.target,
                credential_id=os.environ.get(args.credential_id_env, ""),
                secret=os.environ.get(args.secret_env, "") or os.environ.get("OPENAI_API_KEY", ""),
            )
            print(result + (" [cached]" if cached else ""))
        elif args.command == "save":
            print(store.save_item(
                args.kind, args.source, args.translation, args.context, args.game,
                args.tags, args.group
            ))
        elif args.command == "saved":
            print(json.dumps([dict(item) for item in store.saved_items(args.query, args.group)], ensure_ascii=False))
        elif args.command == "update-saved":
            store.update_saved_item(args.id, args.source, args.translation, args.tags, args.group)
        elif args.command == "delete-saved":
            store.delete_saved_item(args.id)
        elif args.command == "export-saved":
            store.export_saved_items(args.path)
            print(args.path)
        elif args.command == "import-saved":
            print(store.import_saved_items(args.path))
        elif args.command == "due-saved":
            print(json.dumps([dict(item) for item in store.due_saved_items()], ensure_ascii=False))
        elif args.command == "review-saved":
            store.review_saved_item(args.id, args.rating)
        elif args.command == "sync-saved":
            print(store.sync_saved_items(args.directory))
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
