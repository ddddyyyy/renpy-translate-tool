# Ren'Py Translate Tool

Cross-platform core for capturing and translating Ren'Py dialogue without
changing the game's UI. Requires Python 3.9 or newer.

## Desktop development

```sh
cargo run --manifest-path src-tauri/Cargo.toml
```

The current desktop build reuses the Python core and reads the API key from
`OPENAI_API_KEY`. It can install the hook, receive live text, translate either
a selection or the whole sentence, and save the result.

- `Ctrl/Cmd + Shift + Space`: open the selectable in-game overlay.
- `Ctrl/Cmd + Shift + Enter`: translate the current sentence in the overlay.
- `Esc`: close the interactive overlay and return input to the game.

## Install the hook

```sh
python3 -m renpy_translate install "/path/to/RenPy Game"
```

The installer adds only `game/renpy_translate_hook.rpy`. It refuses to
overwrite an existing or modified file.

## Listen and store dialogue

```sh
python3 -m renpy_translate listen
```

Dialogue and choices are accepted only from `127.0.0.1:19840` and stored in
`~/.renpy-translate-tool.sqlite3`.

## Translate

The endpoint must implement OpenAI-compatible `chat/completions`:

```sh
OPENAI_API_KEY=... python3 -m renpy_translate translate "Hello" \
  --base-url https://api.openai.com/v1 \
  --model your-model \
  --target zh-CN
```

Repeated requests with the same endpoint, model, languages, and text reuse the
SQLite cache.

## Save and list words or sentences

```sh
python3 -m renpy_translate save word "Hello" "你好" --context "Hello, world."
python3 -m renpy_translate saved
```

## Uninstall

```sh
python3 -m renpy_translate uninstall "/path/to/RenPy Game"
```

The uninstaller removes only an unmodified tool-owned `.rpy` and its generated
`.rpyc`.

## Check

```sh
python3 -m unittest discover -s tests
```
