#!/usr/bin/env python3
import argparse
import json
import socket

from renpy_translate.core import HOST, PORT, receive_once


def main():
    parser = argparse.ArgumentParser(description="Receive Ren'Py text events")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((HOST, args.port))
        print("Listening on {}:{}".format(HOST, args.port), flush=True)

        while True:
            try:
                event = receive_once(sock)
            except KeyboardInterrupt:
                break
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                print("Ignored packet: {}".format(error), flush=True)
                continue

            print(json.dumps(event, ensure_ascii=False), flush=True)
            if args.once:
                break


if __name__ == "__main__":
    main()
