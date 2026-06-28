//! Lifecycle for the Ormah server daemon.
//!
//! The server runs as an independent daemon (`ormah server start -d`), not
//! as a child of this process — closing the app leaves it running. The app
//! can start/stop it on demand via start_daemon() / stop_daemon().
//!
//! On first launch the bundled `uv` sidecar installs the `ormah` Python
//! package from PyPI. Subsequent launches skip the install and start the
//! server directly. Falls back to a system `ormah` on PATH when the `uv`
//! sidecar is absent (dev builds).

use std::path::PathBuf;
use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_shell::ShellExt;

// Must stay in sync with the Python package version — update on each release.
const ORMAH_VERSION: &str = "0.13.0";

/// Phase emitted on the "ormah://status" event so the UI can show progress.
#[derive(Clone, serde::Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum Phase {
    Installing { version: &'static str },
    Starting,
    Failed { reason: String },
}

pub fn start<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        ensure_running(app).await;
    });
}

async fn ensure_running<R: Runtime>(app: AppHandle<R>) {
    if find_ormah().is_none() {
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
        let _ = app.emit("ormah://status", Phase::Installing { version: ORMAH_VERSION });
        let _ = install_via_uv(&app).await;
    }
    let _ = app.emit("ormah://status", Phase::Starting);
    start_daemon();
}

/// Find the ormah binary. Checks uv tool install locations first (GUI apps
/// don't inherit the user's shell PATH, so ~/.local/bin is often missing),
/// then falls back to a PATH search.
pub fn find_ormah() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;

    let candidates = [
        format!("{home}/.local/bin/ormah"),
        format!("{home}/.local/share/uv/tools/ormah/bin/ormah"),
        format!("{home}/.local/share/mise/shims/ormah"),
        "/usr/local/bin/ormah".to_string(),
        "/opt/homebrew/bin/ormah".to_string(),
    ];

    for path in &candidates {
        let p = PathBuf::from(path);
        if p.exists() {
            return Some(p);
        }
    }

    std::process::Command::new("which")
        .arg("ormah")
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if s.is_empty() { None } else { Some(PathBuf::from(s)) }
            } else {
                None
            }
        })
}

/// Start the ormah server as an independent background daemon.
/// Safe to call when already running — ormah server start is idempotent.
pub fn start_daemon() {
    let Some(bin) = find_ormah() else {
        eprintln!("ormah binary not found — cannot start server");
        return;
    };
    match std::process::Command::new(&bin)
        .args(["server", "start", "-d"])
        .status()
    {
        Ok(s) => eprintln!("ormah server start -d exited {s}"),
        Err(e) => eprintln!("failed to start ormah server ({bin:?}): {e}"),
    }
}

/// Stop the ormah daemon. No-op if not running.
pub fn stop_daemon() {
    let Some(bin) = find_ormah() else { return };
    let _ = std::process::Command::new(&bin)
        .args(["server", "stop"])
        .status();
}

/// Ping /admin/health — true means the server is up and responding.
pub async fn is_running() -> bool {
    let url = format!("{}/admin/health", crate::commands::base_url());
    reqwest::Client::new()
        .get(&url)
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

fn needs_upgrade() -> bool {
    let Some(bin) = find_ormah() else { return false };
    let Ok(out) = std::process::Command::new(bin).arg("--version").output() else {
        return false;
    };
    !String::from_utf8_lossy(&out.stdout).contains(ORMAH_VERSION)
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
    match uv.args(["tool", "install", "--reinstall", &spec]).output().await {
        Ok(out) if out.status.success() => { eprintln!("uv: installed {spec}"); true }
        Ok(out) => {
            eprintln!("uv install failed:\n{}", String::from_utf8_lossy(&out.stderr));
            false
        }
        Err(e) => { eprintln!("uv sidecar error: {e}"); false }
    }
}
