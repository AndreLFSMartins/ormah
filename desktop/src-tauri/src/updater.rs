//! App update checker — runs once on launch, shows a tray/notification prompt.
//!
//! Never silently applies an update. If a new version is available the user
//! sees a notification and a tray menu item; the download + relaunch only
//! happens when they explicitly click "Install update".

use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_updater::UpdaterExt;

/// Emitted to the webview so the UI can show an in-app banner if desired.
#[derive(Clone, serde::Serialize, serde::Deserialize)]
pub struct UpdateAvailable {
    pub version: String,
    pub notes: String,
}

/// Check for an app update in the background. If one is found, notify the
/// user via a system notification and emit `ormah://update-available` to
/// the webview. Does NOT download or apply anything.
pub fn check<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        if let Err(e) = do_check(app).await {
            eprintln!("updater check failed: {e}");
        }
    });
}

async fn do_check<R: Runtime>(app: AppHandle<R>) -> tauri_plugin_updater::Result<()> {
    let updater = app.updater()?;
    let Some(update) = updater.check().await? else {
        return Ok(());
    };

    let version = update.version.clone();
    let notes = update
        .body
        .clone()
        .unwrap_or_default()
        .lines()
        .take(3)
        .collect::<Vec<_>>()
        .join(" ");

    // Emit to the webview so an in-app banner can appear.
    let _ = app.emit(
        "ormah://update-available",
        UpdateAvailable {
            version: version.clone(),
            notes: notes.clone(),
        },
    );

    // Surface a system notification — this reaches the user even if the
    // window is hidden.
    use tauri_plugin_notification::NotificationExt;
    let body = format!("Ormah Desktop {version} is ready. Open the menu to install.");
    let _ = app
        .notification()
        .builder()
        .title("Update available")
        .body(body)
        .show();

    Ok(())
}

/// Download and apply the update, then relaunch. Call this only after the
/// user has explicitly consented (e.g. clicked "Install update" in the tray).
pub fn install<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        if let Err(e) = do_install(app).await {
            eprintln!("update install failed: {e}");
        }
    });
}

async fn do_install<R: Runtime>(app: AppHandle<R>) -> tauri_plugin_updater::Result<()> {
    let updater = app.updater()?;
    let Some(update) = updater.check().await? else {
        return Ok(());
    };

    update
        .download_and_install(
            |_chunk, _total| {},
            || {
                // Relaunch after install. The new binary picks up from here.
                app.restart();
            },
        )
        .await
}
