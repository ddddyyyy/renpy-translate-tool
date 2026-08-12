use std::{
    io::{BufRead, BufReader},
    path::Path,
    process::{Child, Command, Stdio},
    sync::Mutex,
};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition};
use tauri_plugin_global_shortcut::{Shortcut, ShortcutEvent, ShortcutState};

struct Listener(Mutex<Option<Child>>);
struct CurrentText(Mutex<Option<String>>);
struct OverlayMode(Mutex<String>);

fn python() -> &'static str {
    if cfg!(windows) {
        "python"
    } else {
        "python3"
    }
}

fn root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap()
}

fn core(args: &[&str]) -> Result<String, String> {
    let output = Command::new(python())
        .args(["-m", "renpy_translate"])
        .args(args)
        .current_dir(root())
        .output()
        .map_err(|error| error.to_string())?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if output.status.success() {
        Ok(stdout)
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

#[tauri::command]
fn install_hook(path: String) -> Result<String, String> {
    core(&["install", &path])
}

#[tauri::command]
fn uninstall_hook(path: String) -> Result<String, String> {
    core(&["uninstall", &path])
}

#[tauri::command]
fn translate_text(
    text: String,
    base_url: String,
    model: String,
    target: String,
) -> Result<String, String> {
    core(&[
        "translate",
        &text,
        "--base-url",
        &base_url,
        "--model",
        &model,
        "--target",
        &target,
    ])
}

#[tauri::command]
fn save_item(
    kind: String,
    source: String,
    translation: String,
    context: String,
    game: String,
) -> Result<String, String> {
    core(&[
        "save",
        &kind,
        &source,
        &translation,
        "--context",
        &context,
        "--game",
        &game,
    ])
}

#[tauri::command]
fn close_overlay(app: AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("overlay")
        .ok_or("overlay window is unavailable")?;
    window
        .set_ignore_cursor_events(true)
        .and_then(|_| window.hide())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn current_text(app: AppHandle) -> Option<String> {
    app.state::<CurrentText>().0.lock().unwrap().clone()
}

#[tauri::command]
fn current_overlay_mode(app: AppHandle) -> String {
    app.state::<OverlayMode>().0.lock().unwrap().clone()
}

fn show_overlay(app: &AppHandle, mode: &str, interactive: bool) {
    *app.state::<OverlayMode>().0.lock().unwrap() = mode.to_owned();
    if let Some(window) = app.get_webview_window("overlay") {
        if interactive {
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.minimize();
            }
        }
        let _ = window.set_ignore_cursor_events(!interactive);
        let _ = window.show();
        if interactive {
            let _ = window.set_focus();
        }
        if let Some(text) = app.state::<CurrentText>().0.lock().unwrap().clone() {
            let _ = window.emit("text-event", text);
        }
        let _ = window.emit("overlay-mode", mode);
    }
}

fn position_overlay(app: &AppHandle) {
    let Some(window) = app.get_webview_window("overlay") else {
        return;
    };
    let (Ok(Some(monitor)), Ok(size)) = (window.primary_monitor(), window.outer_size()) else {
        return;
    };
    let area = monitor.work_area();
    let x = area.position.x + (area.size.width.saturating_sub(size.width) / 2) as i32;
    let y = area.position.y + area.size.height.saturating_sub(size.height + 72) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            app.manage(CurrentText(Mutex::new(None)));
            app.manage(OverlayMode(Mutex::new("select".to_owned())));
            // ponytail: development uses system Python; bundle a sidecar when shipping installers.
            let mut child = Command::new(python())
                .args(["-m", "renpy_translate", "listen"])
                .current_dir(root())
                .stdout(Stdio::piped())
                .spawn()?;
            let stdout = child.stdout.take().unwrap();
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    if line.starts_with('{') {
                        *handle.state::<CurrentText>().0.lock().unwrap() = Some(line.clone());
                        let _ = handle.emit("text-event", line);
                    }
                }
            });
            app.manage(Listener(Mutex::new(Some(child))));

            position_overlay(app.handle());
            let select: Shortcut = "CmdOrCtrl+Shift+Space".parse()?;
            let sentence: Shortcut = "CmdOrCtrl+Shift+Enter".parse()?;
            let select_id = select.id();
            let sentence_id = sentence.id();
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_shortcuts([select, sentence])?
                    .with_handler(move |app, shortcut, ShortcutEvent { state, .. }| {
                        if state != ShortcutState::Pressed {
                            return;
                        }
                        if shortcut.id() == select_id {
                            show_overlay(app, "select", true);
                        } else if shortcut.id() == sentence_id {
                            show_overlay(app, "sentence", false);
                        }
                    })
                    .build(),
            )?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            install_hook,
            uninstall_hook,
            translate_text,
            save_item,
            close_overlay,
            current_text,
            current_overlay_mode
        ])
        .build(tauri::generate_context!())
        .expect("failed to build application");

    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Some(mut child) = handle.state::<Listener>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
