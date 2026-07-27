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

// Injected by build.rs from the repo's pyproject.toml, so the pinned Python
// package version can never drift from the released one.
const ORMAH_VERSION: &str = env!("ORMAH_PY_VERSION");

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
    let installed = find_ormah().is_some();
    let runtime_action = choose_runtime_action(installed, installed && needs_upgrade());
    let runtime_changed = match runtime_action {
        RuntimeAction::Install | RuntimeAction::Upgrade => {
            let _ = app.emit(
                "ormah://status",
                Phase::Installing {
                    version: ORMAH_VERSION,
                },
            );
            if !install_via_uv(&app).await {
                let _ = app.emit(
                    "ormah://status",
                    Phase::Failed {
                        reason: "Could not install ormah. Check your internet connection.".into(),
                    },
                );
                return;
            }
            true
        }
        RuntimeAction::Reuse => false,
    };

    // A uv reinstall replaces files on disk but cannot replace modules in the already-running
    // daemon. Restart after successful install/upgrade so migrations and model provisioning run
    // under the newly pinned Python package.
    if runtime_changed {
        stop_daemon();
    }
    let _ = app.emit("ormah://status", Phase::Starting);
    start_daemon();
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RuntimeAction {
    Install,
    Upgrade,
    Reuse,
}

fn choose_runtime_action(installed: bool, upgrade_needed: bool) -> RuntimeAction {
    if !installed {
        RuntimeAction::Install
    } else if upgrade_needed {
        RuntimeAction::Upgrade
    } else {
        RuntimeAction::Reuse
    }
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
    match clean_python_env(std::process::Command::new(&bin))
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
    let _ = clean_python_env(std::process::Command::new(&bin))
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
    let Ok(out) = clean_python_env(std::process::Command::new(bin))
        .arg("--version")
        .output()
    else {
        return false;
    };
    if !out.status.success() {
        return true;
    }
    should_upgrade(&out.stdout, ORMAH_VERSION)
}

fn should_upgrade(output: &[u8], required: &str) -> bool {
    let Ok(required) = semver::Version::parse(required) else {
        return true;
    };
    let installed = String::from_utf8_lossy(output)
        .split_whitespace()
        .find_map(|word| semver::Version::parse(word).ok());
    match installed {
        Some(installed) => installed < required,
        None => true,
    }
}

/// Remove Python env vars that AppImage sets and that corrupt child Python runtimes.
/// AppImage mounts itself and sets PYTHONHOME/PYTHONPATH to paths inside the
/// mount — any subprocess that spawns Python inherits them and fails to find
/// the stdlib with "No module named 'encodings'".
fn clean_python_env(mut cmd: std::process::Command) -> std::process::Command {
    for var in &["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE"] {
        cmd.env_remove(var);
    }
    cmd
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

#[cfg(test)]
mod tests {
    use super::{choose_runtime_action, should_upgrade, RuntimeAction};

    #[test]
    fn installs_when_runtime_is_missing() {
        assert_eq!(choose_runtime_action(false, false), RuntimeAction::Install);
    }

    #[test]
    fn upgrades_when_installed_runtime_is_old() {
        assert_eq!(choose_runtime_action(true, true), RuntimeAction::Upgrade);
    }

    #[test]
    fn reuses_matching_or_newer_runtime() {
        assert_eq!(choose_runtime_action(true, false), RuntimeAction::Reuse);
    }

    #[test]
    fn upgrades_an_older_cli() {
        assert!(should_upgrade(b"ormah 0.13.6\n", "0.14.0"));
    }

    #[test]
    fn leaves_the_pinned_cli_unchanged() {
        assert!(!should_upgrade(b"ormah 0.14.0\n", "0.14.0"));
    }

    #[test]
    fn never_downgrades_a_newer_cli() {
        assert!(!should_upgrade(b"ormah 0.15.0\n", "0.14.0"));
    }

    #[test]
    fn repairs_unparseable_version_output() {
        assert!(should_upgrade(b"unknown\n", "0.14.0"));
    }
}
