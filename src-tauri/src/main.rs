use std::{
    io::{BufRead, BufReader},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::{menu::MenuBuilder, tray::TrayIconBuilder};
use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutEvent, ShortcutState};
use tauri_plugin_opener::OpenerExt;

struct Listener {
    child: Mutex<Option<Child>>,
    stop: AtomicBool,
}
struct CurrentText(Mutex<Option<String>>);
struct OverlayMode(Mutex<String>);
struct Shortcuts(Mutex<(Shortcut, Shortcut)>);
struct TranslationProcess(Mutex<Option<Child>>);

const KEYRING_SERVICE: &str = "dev.renpy-translate-tool";
const KEYRING_USER: &str = "translation-api-key";

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
    core_with_credentials(args, None, None)
}

fn core_with_credentials(
    args: &[&str],
    credential_id: Option<&str>,
    secret: Option<&str>,
) -> Result<String, String> {
    let mut command = Command::new(python());
    command
        .args(["-m", "renpy_translate"])
        .args(args)
        .current_dir(root());
    if let Some(credential_id) = credential_id {
        command.env("TRANSLATION_CREDENTIAL_ID", credential_id);
    }
    if let Some(secret) = secret {
        command.env("TRANSLATION_SECRET", secret);
    }
    let output = command.output().map_err(|error| error.to_string())?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    if output.status.success() {
        Ok(stdout)
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

fn translation_core(
    app: &AppHandle,
    args: &[&str],
    credential_id: Option<&str>,
    secret: Option<&str>,
) -> Result<String, String> {
    let mut command = Command::new(python());
    command
        .args(["-m", "renpy_translate"])
        .args(args)
        .current_dir(root())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(credential_id) = credential_id {
        command.env("TRANSLATION_CREDENTIAL_ID", credential_id);
    }
    if let Some(secret) = secret {
        command.env("TRANSLATION_SECRET", secret);
    }
    let state = app.state::<TranslationProcess>();
    let mut slot = state.0.lock().unwrap();
    if slot.is_some() {
        return Err("another translation is already running".to_owned());
    }
    *slot = Some(command.spawn().map_err(|error| error.to_string())?);
    drop(slot);

    loop {
        std::thread::sleep(Duration::from_millis(30));
        let mut slot = state.0.lock().unwrap();
        let Some(child) = slot.as_mut() else {
            return Err("translation canceled".to_owned());
        };
        if child
            .try_wait()
            .map_err(|error| error.to_string())?
            .is_some()
        {
            let child = slot.take().unwrap();
            drop(slot);
            let output = child
                .wait_with_output()
                .map_err(|error| error.to_string())?;
            let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
            return if output.status.success() {
                Ok(stdout)
            } else {
                Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
            };
        }
    }
}

fn credential_entry(provider: &str, field: &str) -> Result<keyring::Entry, String> {
    if !matches!(provider, "openai" | "deepl" | "google" | "baidu" | "youdao") {
        return Err("unsupported translation provider".to_owned());
    }
    let user = if provider == "openai" && field == "secret" {
        KEYRING_USER.to_owned()
    } else {
        format!("translation-{provider}-{field}")
    };
    keyring::Entry::new(KEYRING_SERVICE, &user).map_err(|error| error.to_string())
}

fn stored_credential(provider: &str, field: &str) -> Result<Option<String>, String> {
    match credential_entry(provider, field)?.get_password() {
        Ok(password) => Ok(Some(password)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn credential_status(provider: String) -> Result<String, String> {
    Ok(format!(
        "{{\"id\":{},\"secret\":{}}}",
        stored_credential(&provider, "id")?.is_some(),
        stored_credential(&provider, "secret")?.is_some()
    ))
}

#[tauri::command]
fn set_provider_credentials(
    provider: String,
    credential_id: String,
    secret: String,
) -> Result<(), String> {
    if secret.trim().is_empty() {
        return Err("credential secret cannot be empty".to_owned());
    }
    let needs_id = matches!(provider.as_str(), "baidu" | "youdao");
    if needs_id && credential_id.trim().is_empty() {
        return Err("App ID/Key cannot be empty".to_owned());
    }
    credential_entry(&provider, "secret")?
        .set_password(secret.trim())
        .map_err(|error| error.to_string())?;
    if needs_id {
        credential_entry(&provider, "id")?
            .set_password(credential_id.trim())
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn clear_provider_credentials(provider: String) -> Result<(), String> {
    for field in ["id", "secret"] {
        match credential_entry(&provider, field)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => {}
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(())
}

#[tauri::command]
fn resize_overlay(app: AppHandle, width: f64, height: f64) -> Result<(), String> {
    if !width.is_finite() || !height.is_finite() {
        return Err("invalid overlay size".to_owned());
    }
    let window = app
        .get_webview_window("overlay")
        .ok_or("overlay window is unavailable")?;
    let size = LogicalSize::new(width.clamp(500.0, 2400.0), height.clamp(140.0, 1400.0));
    let physical_size = size.to_physical(window.scale_factor().map_err(|error| error.to_string())?);
    window.set_size(size).map_err(|error| error.to_string())?;
    position_overlay(&app, Some(physical_size));
    Ok(())
}

#[tauri::command]
fn restore_overlay(app: AppHandle, width: f64, height: f64, x: i32, y: i32) -> Result<(), String> {
    if !width.is_finite() || !height.is_finite() {
        return Err("invalid overlay geometry".to_owned());
    }
    let window = app
        .get_webview_window("overlay")
        .ok_or("overlay window is unavailable")?;
    let logical = LogicalSize::new(width.clamp(500.0, 2400.0), height.clamp(140.0, 1400.0));
    let physical = logical.to_physical(window.scale_factor().map_err(|error| error.to_string())?);
    let monitors = window
        .available_monitors()
        .map_err(|error| error.to_string())?;
    let monitor = monitors
        .iter()
        .find(|monitor| {
            let area = monitor.work_area();
            x >= area.position.x
                && y >= area.position.y
                && x < area.position.x + area.size.width as i32
                && y < area.position.y + area.size.height as i32
        })
        .or(monitors.first())
        .ok_or("no monitor is available")?;
    let area = monitor.work_area();
    let max_x = (area.position.x + area.size.width.saturating_sub(physical.width) as i32)
        .max(area.position.x);
    let max_y = (area.position.y + area.size.height.saturating_sub(physical.height) as i32)
        .max(area.position.y);
    window
        .set_size(logical)
        .map_err(|error| error.to_string())?;
    window
        .set_position(PhysicalPosition::new(
            x.clamp(area.position.x, max_x),
            y.clamp(area.position.y, max_y),
        ))
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn pick_directory(app: AppHandle) -> Result<Option<String>, String> {
    Ok(app
        .dialog()
        .file()
        .blocking_pick_folder()
        .map(|path| {
            path.into_path()
                .map(|path| path.to_string_lossy().into_owned())
        })
        .transpose()
        .map_err(|error| error.to_string())?)
}

#[tauri::command]
fn set_shortcuts(app: AppHandle, select: String, sentence: String) -> Result<(), String> {
    let select: Shortcut = select
        .parse()
        .map_err(|error| format!("invalid select shortcut: {error}"))?;
    let sentence: Shortcut = sentence
        .parse()
        .map_err(|error| format!("invalid sentence shortcut: {error}"))?;
    if select.id() == sentence.id() {
        return Err("the two shortcuts must be different".to_owned());
    }
    let global = app.global_shortcut();
    let shortcuts = app.state::<Shortcuts>();
    let mut current = shortcuts.0.lock().unwrap();
    global
        .unregister_multiple([current.0, current.1])
        .map_err(|error| error.to_string())?;
    if let Err(error) = global.register_multiple([select, sentence]) {
        let _ = global.register_multiple([current.0, current.1]);
        return Err(format!("shortcut is unavailable: {error}"));
    }
    *current = (select, sentence);
    Ok(())
}

#[tauri::command]
fn check_update() -> Result<String, String> {
    core(&["check-update", env!("CARGO_PKG_VERSION")])
}

#[tauri::command]
fn open_release(app: AppHandle, url: String) -> Result<(), String> {
    if !url.starts_with("https://github.com/ddddyyyy/renpy-translate-tool/releases/") {
        return Err("untrusted release URL".to_owned());
    }
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|error| error.to_string())
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
async fn translate_text(
    app: AppHandle,
    text: String,
    provider: String,
    base_url: String,
    model: String,
    target: String,
) -> Result<String, String> {
    let credential_id = stored_credential(&provider, "id")?;
    let secret = stored_credential(&provider, "secret")?;
    tauri::async_runtime::spawn_blocking(move || {
        translation_core(
            &app,
            &[
                "translate",
                &text,
                "--provider",
                &provider,
                "--base-url",
                &base_url,
                "--model",
                &model,
                "--target",
                &target,
            ],
            credential_id.as_deref(),
            secret.as_deref(),
        )
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
fn cancel_translation(app: AppHandle) -> Result<(), String> {
    if let Some(mut child) = app.state::<TranslationProcess>().0.lock().unwrap().take() {
        child
            .kill()
            .and_then(|_| child.wait())
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn lookup_word(word: String) -> Result<String, String> {
    core(&["lookup", &word])
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
fn list_saved(query: String) -> Result<String, String> {
    core(&["saved", "--query", &query])
}

#[tauri::command]
fn update_saved(id: i64, source: String, translation: String) -> Result<String, String> {
    core(&["update-saved", &id.to_string(), &source, &translation])
}

#[tauri::command]
fn delete_saved(id: i64) -> Result<String, String> {
    core(&["delete-saved", &id.to_string()])
}

#[tauri::command]
fn export_saved() -> Result<String, String> {
    let home = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(std::path::PathBuf::from)
        .unwrap_or(std::env::current_dir().map_err(|error| error.to_string())?);
    let directory = if home.join("Desktop").is_dir() {
        home.join("Desktop")
    } else {
        home
    };
    let path = (0..)
        .map(|index| {
            directory.join(if index == 0 {
                "renpy-translate-wordbook.csv".to_owned()
            } else {
                format!("renpy-translate-wordbook-{index}.csv")
            })
        })
        .find(|path| !path.exists())
        .unwrap();
    core(&["export-saved", &path.to_string_lossy()])
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

fn position_overlay(app: &AppHandle, size: Option<PhysicalSize<u32>>) {
    let Some(window) = app.get_webview_window("overlay") else {
        return;
    };
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return;
    };
    let size = match size {
        Some(size) => size,
        None => match window.outer_size() {
            Ok(size) => size,
            Err(_) => return,
        },
    };
    let area = monitor.work_area();
    let x = area.position.x + (area.size.width.saturating_sub(size.width) / 2) as i32;
    let y = area.position.y + area.size.height.saturating_sub(size.height + 72) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            app.manage(CurrentText(Mutex::new(None)));
            app.manage(OverlayMode(Mutex::new("select".to_owned())));
            app.manage(TranslationProcess(Mutex::new(None)));
            app.manage(Listener {
                child: Mutex::new(None),
                stop: AtomicBool::new(false),
            });
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                while !handle.state::<Listener>().stop.load(Ordering::Relaxed) {
                    // ponytail: development uses system Python; bundle a sidecar when shipping installers.
                    let Ok(mut child) = Command::new(python())
                        .args(["-m", "renpy_translate", "listen"])
                        .current_dir(root())
                        .stdout(Stdio::piped())
                        .spawn()
                    else {
                        std::thread::sleep(Duration::from_secs(2));
                        continue;
                    };
                    let stdout = child.stdout.take().unwrap();
                    *handle.state::<Listener>().child.lock().unwrap() = Some(child);
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        if line.starts_with('{') {
                            *handle.state::<CurrentText>().0.lock().unwrap() = Some(line.clone());
                            let _ = handle.emit("text-event", line);
                        }
                    }
                    handle.state::<Listener>().child.lock().unwrap().take();
                    std::thread::sleep(Duration::from_secs(1));
                }
            });

            position_overlay(app.handle(), None);
            let select: Shortcut = "CmdOrCtrl+Shift+Space".parse()?;
            let sentence: Shortcut = "CmdOrCtrl+Shift+Enter".parse()?;
            app.manage(Shortcuts(Mutex::new((select, sentence))));
            app.handle().plugin(
                tauri_plugin_global_shortcut::Builder::new()
                    .with_shortcuts([select, sentence])?
                    .with_handler(move |app, shortcut, ShortcutEvent { state, .. }| {
                        if state != ShortcutState::Pressed {
                            return;
                        }
                        let state = app.state::<Shortcuts>();
                        let shortcuts = state.0.lock().unwrap();
                        if shortcut.id() == shortcuts.0.id() {
                            show_overlay(app, "select", true);
                        } else if shortcut.id() == shortcuts.1.id() {
                            show_overlay(app, "sentence", false);
                        }
                    })
                    .build(),
            )?;
            let menu = MenuBuilder::new(app)
                .text("show", "显示主窗口")
                .text("select", "选词翻译")
                .text("sentence", "整句翻译")
                .separator()
                .text("quit", "退出")
                .build()?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Ren'Py Translate")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window
                                .unminimize()
                                .and_then(|_| window.show())
                                .and_then(|_| window.set_focus());
                        }
                    }
                    "select" => show_overlay(app, "select", true),
                    "sentence" => show_overlay(app, "sentence", false),
                    "quit" => app.exit(0),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            install_hook,
            uninstall_hook,
            credential_status,
            set_provider_credentials,
            clear_provider_credentials,
            resize_overlay,
            restore_overlay,
            pick_directory,
            set_shortcuts,
            check_update,
            open_release,
            translate_text,
            cancel_translation,
            lookup_word,
            save_item,
            list_saved,
            update_saved,
            delete_saved,
            export_saved,
            close_overlay,
            current_text,
            current_overlay_mode
        ])
        .build(tauri::generate_context!())
        .expect("failed to build application");

    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            handle
                .state::<Listener>()
                .stop
                .store(true, Ordering::Relaxed);
            if let Some(mut child) = handle.state::<Listener>().child.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    #[test]
    fn system_keyring_round_trip() {
        let openai =
            keyring::Entry::new(super::KEYRING_SERVICE, "translation-test-openai").unwrap();
        let deepl = keyring::Entry::new(super::KEYRING_SERVICE, "translation-test-deepl").unwrap();
        for entry in [&openai, &deepl] {
            let _ = entry.delete_credential();
        }
        openai.set_password("openai-secret").unwrap();
        deepl.set_password("deepl-secret").unwrap();
        assert_eq!(openai.get_password().unwrap(), "openai-secret");
        assert_eq!(deepl.get_password().unwrap(), "deepl-secret");
        for entry in [&openai, &deepl] {
            entry.delete_credential().unwrap();
        }
    }
}
