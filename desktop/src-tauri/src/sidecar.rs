//! Lifecycle for the bundled `ormah-server` sidecar (the frozen Python server).

use std::sync::Mutex;

use once_cell::sync::Lazy;
use tauri::{AppHandle, Runtime};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

static CHILD: Lazy<Mutex<Option<CommandChild>>> = Lazy::new(|| Mutex::new(None));

/// Spawn `ormah-server server start` and hold the child so we can kill it on
/// quit. Runs the read loop so the OS pipe buffer never fills and stalls it.
pub fn start<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        let cmd = match app.shell().sidecar("ormah-server") {
            Ok(c) => c.args(["server", "start"]),
            Err(e) => {
                eprintln!("ormah sidecar not found: {e}");
                return;
            }
        };
        match cmd.spawn() {
            Ok((mut rx, child)) => {
                *CHILD.lock().unwrap() = Some(child);
                // Drain events; could be forwarded to a log file in v1.1.
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Terminated(payload) = event {
                        eprintln!("ormah server exited: {:?}", payload);
                        *CHILD.lock().unwrap() = None;
                        break;
                    }
                }
            }
            Err(e) => eprintln!("failed to spawn ormah server: {e}"),
        }
    });
}

/// Kill the bundled server. Safe to call multiple times.
pub fn stop() {
    if let Some(child) = CHILD.lock().unwrap().take() {
        let _ = child.kill();
    }
}
