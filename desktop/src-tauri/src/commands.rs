//! Tauri commands + small helpers shared by the tray and the onboarding webview.

use serde_json::Value;
use tauri::{AppHandle, Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::ShellExt;

use crate::stats::{self, Stats};

/// Base URL of the bundled server. Honors `ORMAH_PORT`, defaults to 8787.
pub fn base_url() -> String {
    let port = std::env::var("ORMAH_PORT").unwrap_or_else(|_| "8787".to_string());
    format!("http://127.0.0.1:{port}")
}

// ---- graph -----------------------------------------------------------------

pub fn open_graph<R: Runtime>(app: &AppHandle<R>) {
    let _ = app.shell().open(base_url(), None);
}

#[tauri::command]
pub fn open_graph_cmd<R: Runtime>(app: AppHandle<R>) {
    open_graph(&app);
}

// ---- stats -----------------------------------------------------------------

#[tauri::command]
pub async fn fetch_stats() -> Result<Stats, String> {
    stats::fetch().await.map_err(|e| e.to_string())
}

// ---- agent setup -----------------------------------------------------------

/// Run the bundled `ormah setup --json` and return its parsed result.
#[tauri::command]
pub async fn setup_agents<R: Runtime>(app: AppHandle<R>) -> Result<Value, String> {
    let output = app
        .shell()
        .sidecar("ormah-server")
        .map_err(|e| e.to_string())?
        .args(["setup", "--json"])
        .output()
        .await
        .map_err(|e| e.to_string())?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str::<Value>(&stdout).map_err(|e| {
        format!(
            "could not parse setup output: {e}\nstdout: {stdout}\nstderr: {}",
            String::from_utf8_lossy(&output.stderr)
        )
    })
}

/// Tray-triggered variant: run setup off-thread and surface a notification.
pub fn run_setup_notify<R: Runtime>(app: AppHandle<R>) {
    tauri::async_runtime::spawn(async move {
        let (title, body) = match setup_agents(app.clone()).await {
            Ok(v) => {
                let wired = v
                    .get("wired")
                    .and_then(|w| w.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .unwrap_or_default();
                if wired.is_empty() {
                    (
                        "No agents found",
                        "Install Claude Code, Claude Desktop, or Codex, then try again."
                            .to_string(),
                    )
                } else {
                    ("Agents wired up", format!("Connected: {wired}"))
                }
            }
            Err(e) => ("Setup failed", e),
        };
        let _ = app
            .notification()
            .builder()
            .title(title)
            .body(body)
            .show();
    });
}

// ---- onboarding marker -----------------------------------------------------

fn marker_path<R: Runtime>(app: &AppHandle<R>) -> Option<std::path::PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|d| d.join("onboarded"))
}

pub fn onboarded<R: Runtime>(app: &AppHandle<R>) -> bool {
    marker_path(app).map(|p| p.exists()).unwrap_or(false)
}

#[tauri::command]
pub fn is_onboarded<R: Runtime>(app: AppHandle<R>) -> bool {
    onboarded(&app)
}

#[tauri::command]
pub fn mark_onboarded<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    if let Some(p) = marker_path(&app) {
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::write(&p, b"1").map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn open_onboarding<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    WebviewWindowBuilder::new(app, "onboarding", WebviewUrl::App("index.html".into()))
        .title("Welcome to Ormah")
        .inner_size(520.0, 620.0)
        .resizable(false)
        .center()
        .build()?;
    Ok(())
}
