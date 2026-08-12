init 999 python:
    import json
    import socket

    _rtt_address = ("127.0.0.1", 19840)
    _rtt_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _rtt_socket.setblocking(False)

    def _rtt_plain_text(value):
        if not value:
            return ""
        return renpy.filter_text_tags(value, allow=[]).strip()

    def _rtt_send(event, text, who=""):
        try:
            text = _rtt_plain_text(text)
            if not text:
                return

            payload = json.dumps({
                "protocol": 1,
                "event": event,
                "game": config.name,
                "game_version": config.version,
                "who": _rtt_plain_text(who),
                "text": text,
            }, ensure_ascii=False).encode("utf-8")
            _rtt_socket.sendto(payload, _rtt_address)
        except Exception:
            # The translator must never interfere with the game.
            pass

    def _rtt_capture_dialogue(entry):
        if getattr(entry, "kind", None) == "current":
            _rtt_send("dialogue", entry.what, entry.who)

    _rtt_previous_text_filter = config.say_menu_text_filter

    def _rtt_capture_choices(text):
        if _rtt_previous_text_filter is not None:
            text = _rtt_previous_text_filter(text)

        if renpy.ast.current_statement_name.startswith("menu"):
            _rtt_send("choice", text)
        return text

    config.history_callbacks.append(_rtt_capture_dialogue)
    config.say_menu_text_filter = _rtt_capture_choices

