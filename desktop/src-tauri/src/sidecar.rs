//! Lifecycle for the Ormah server.
//!
//! Distribution builds ship a frozen `ormah-server` sidecar (self-contained,
//! no system Python). During development — and on platforms where the sidecar
//! isn't bundled yet — we fall back to an `ormah` already on PATH so the app
//! runs end-to-end today.

use std::sync::Mutex;

use once_cell::sync::Lazy;
use tauri::{AppHandle, Runtime};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

/// Whatever we spawned, so we can kill it on quit.
enum Server {
    Bundled(CommandChild),
    System(std::process::Child),
}

static SERVER: Lazy<Mutex<Option<Server>>> = Lazy::new(|| Mutex::new(None));

/// Start the server: bundled sidecar if it spawns, else system `ormah`.
pub fn start<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        if !try_bundled(&app) {
            spawn_system();
        }
    });
}

/// Returns true only if the bundled sidecar actually spawned. The lookup can
/// succeed while the spawn fails (no binary in dev builds), so both are guarded.
fn try_bundled<R: Runtime>(app: &AppHandle<R>) -> bool {
    let cmd = match app.shell().sidecar("ormah-server") {
        Ok(c) => c,
        Err(_) => return false,
    };
    match cmd.args(["server", "start"]).spawn() {
        Ok((mut rx, child)) => {
            *SERVER.lock().unwrap() = Some(Server::Bundled(child));
            // Drain events so the pipe never stalls; clear on exit.
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Terminated(payload) = event {
                        eprintln!("ormah server exited: {payload:?}");
                        *SERVER.lock().unwrap() = None;
                        break;
                    }
                }
            });
            true
        }
        Err(e) => {
            eprintln!("bundled sidecar present but spawn failed ({e}); trying system ormah");
            false
        }
    }
}

fn spawn_system() {
    match std::process::Command::new("ormah")
        .args(["server", "start"])
        .spawn()
    {
        Ok(child) => {
            eprintln!("started system `ormah` server (no bundled sidecar)");
            *SERVER.lock().unwrap() = Some(Server::System(child));
        }
        Err(e) => eprintln!("no bundled sidecar and no system `ormah` on PATH: {e}"),
    }
}

/// Kill the server. Safe to call multiple times.
pub fn stop() {
    if let Some(server) = SERVER.lock().unwrap().take() {
        match server {
            Server::Bundled(child) => {
                let _ = child.kill();
            }
            Server::System(mut child) => {
                let _ = child.kill();
            }
        }
    }
}
