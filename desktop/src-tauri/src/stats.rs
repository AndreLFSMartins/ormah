//! Poll the bundled server's `/agent/stats` and surface the counter.

use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{menu::MenuItem, tray::TrayIcon, AppHandle, Runtime};

use crate::commands::base_url;

/// Mirror of the JSON returned by `GET /agent/stats`. Unknown fields
/// (window_days, generated_at) are ignored by serde.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stats {
    pub whispers_used_this_week: i64,
    pub whispers_used_total: i64,
    pub memories_this_week: i64,
    pub memories_total: i64,
}

fn fmt_num(n: i64) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().rev().enumerate() {
        if i > 0 && i % 3 == 0 { out.push(','); }
        out.push(c);
    }
    out.chars().rev().collect()
}

pub async fn fetch() -> Result<Stats, reqwest::Error> {
    let url = format!("{}/agent/stats", base_url());
    reqwest::Client::new()
        .get(url)
        .timeout(Duration::from_secs(5))
        .send()
        .await?
        .json::<Stats>()
        .await
}

fn server_status_label(running: bool) -> &'static str {
    if running { "Server: running  ●" } else { "Server: stopped  ○" }
}

fn server_toggle_label(running: bool) -> &'static str {
    if running { "Stop server" } else { "Start server" }
}

/// Background loop: refresh tray title, stat lines, and server status every 60s.
pub fn spawn_poller<R: Runtime>(
    _app: AppHandle<R>,
    tray: TrayIcon<R>,
    week_item: MenuItem<R>,
    total_item: MenuItem<R>,
    server_status: MenuItem<R>,
    server_toggle: MenuItem<R>,
) {
    tauri::async_runtime::spawn(async move {
        loop {
            let running = crate::sidecar::is_running().await;
            let _ = server_status.set_text(server_status_label(running));
            let _ = server_toggle.set_text(server_toggle_label(running));

            if running {
                if let Ok(s) = fetch().await {
                    let _ = tray.set_title(Some(s.whispers_used_this_week.to_string()));
                    let _ = week_item.set_text(format!(
                        "{} whispers this week",
                        s.whispers_used_this_week
                    ));
                    let _ = total_item.set_text(format!(
                        "{}  all-time  ·  {}  memories",
                        fmt_num(s.whispers_used_total),
                        fmt_num(s.memories_total)
                    ));
                }
            } else {
                let _ = tray.set_title(Some("—".to_string()));
            }

            tokio::time::sleep(Duration::from_secs(60)).await;
        }
    });
}
