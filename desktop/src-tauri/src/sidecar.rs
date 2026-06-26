//! Lifecycle for the Ormah server.
//!
//! On first launch the bundled `uv` sidecar installs the `ormah` Python
//! package from PyPI. Subsequent launches skip the install and start the
//! server directly. Falls back to a system `ormah` on PATH when the `uv`
//! sidecar is absent (dev builds).

use once_cell::sync::Lazy;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_shell::ShellExt;

// Must stay in sync with the Python package version — update on each release.
const ORMAH_VERSION: &str = "0.12.4";

/// Phase emitted on the "ormah://status" event so the UI can show progress.
#[derive(Clone, serde::Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum Phase {
    Installing { version: &'static str },
    Starting,
    Failed { reason: String },
}

static SERVER: Lazy<Mutex<Option<std::process::Child>>> = Lazy::new(|| Mutex::new(None));

pub fn start<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        ensure_running(app).await;
    });
}

async fn ensure_running<R: Runtime>(app: AppHandle<R>) {
    if !ormah_on_path() {
        // First launch: install ormah via the bundled uv sidecar.
        let _ = app.emit("ormah://status", Phase::Installing { version: ORMAH_VERSION });
        if !install_via_uv(&app).await {
            let _ = app.emit(
                "ormah://status",
                Phase::Failed {
                    reason: "Could not install ormah. Check your internet connection.".into(),
                },
            );
            return;
        }
    } else if needs_upgrade() {
        // App was updated: upgrade the Python package to the matching version.
        let _ = app.emit("ormah://status", Phase::Installing { version: ORMAH_VERSION });
        // Best-effort — if upgrade fails we still start with the old version.
        let _ = install_via_uv(&app).await;
    }
    let _ = app.emit("ormah://status", Phase::Starting);
    spawn_server();
}

/// Returns true when the installed ormah version doesn't match ORMAH_VERSION.
fn needs_upgrade() -> bool {
    let Ok(out) = std::process::Command::new("ormah")
        .arg("--version")
        .output()
    else {
        return false;
    };
    let installed = String::from_utf8_lossy(&out.stdout);
    // `ormah --version` outputs e.g. "ormah 0.12.4"
    !installed.contains(ORMAH_VERSION)
}

async fn install_via_uv<R: Runtime>(app: &AppHandle<R>) -> bool {
    let uv = match app.shell().sidecar("uv") {
        Ok(c) => c,
        Err(e) => {
            eprintln!("uv sidecar not available ({e}); ormah must be on PATH");
            return false;
        }
    };
    let spec = format!("ormah=={}", ORMAH_VERSION);
    match uv.args(["tool", "install", &spec]).output().await {
        Ok(out) if out.status.success() => {
            eprintln!("uv: installed {}", spec);
            true
        }
        Ok(out) => {
            eprintln!(
                "uv install failed:\n{}",
                String::from_utf8_lossy(&out.stderr)
            );
            false
        }
        Err(e) => {
            eprintln!("uv sidecar error: {e}");
            false
        }
    }
}

fn ormah_on_path() -> bool {
    std::process::Command::new("ormah")
        .arg("--version")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn spawn_server() {
    match std::process::Command::new("ormah")
        .args(["server", "start"])
        .spawn()
    {
        Ok(child) => {
            eprintln!("ormah server started (pid {})", child.id());
            *SERVER.lock().unwrap() = Some(child);
        }
        Err(e) => eprintln!("failed to start ormah server: {e}"),
    }
}

/// Kill the server. Safe to call multiple times.
pub fn stop() {
    if let Some(mut child) = SERVER.lock().unwrap().take() {
        let _ = child.kill();
    }
}
