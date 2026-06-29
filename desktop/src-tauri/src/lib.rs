//! Ormah menubar app (Tauri v2).
//!
//! Ruthlessly minimal per F10: a tray icon whose title is the weekly
//! whispers-used count (the felt-value counter, F09), a dropdown with the
//! stats + actions, a bundled server sidecar, and one-click agent setup.
//! No global hotkey, no native graph, no settings beyond start-at-login.

mod commands;
mod sidecar;
mod stats;
mod tray;
mod updater;

use tauri::{WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

// Hide scrollbar chrome across every page the webview loads (the install shell
// *and* the graph it navigates to). Scrolling still works; only the visual bar
// is removed — kills the spurious horizontal scrollbar on the graph view.
const HIDE_SCROLLBARS: &str = r#"
(function () {
  var css = '::-webkit-scrollbar{width:0!important;height:0!important;background:transparent!important}'
          + 'html{scrollbar-width:none!important;-ms-overflow-style:none!important}';
  var apply = function () {
    if (document.getElementById('__ormah_noscroll')) return;
    var s = document.createElement('style');
    s.id = '__ormah_noscroll';
    s.appendChild(document.createTextNode(css));
    (document.head || document.documentElement).appendChild(s);
  };
  apply();
  document.addEventListener('DOMContentLoaded', apply);
})();
"#;

// Marks the webview as running inside the desktop app on every page load —
// including after navigating to http://localhost:8787 where window.__TAURI__
// is not injected (remote URL). The UI checks this to apply in-app styles.
const MARK_IN_APP: &str = "window.__ORMAH_DESKTOP__ = true;";

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .invoke_handler(tauri::generate_handler![
            commands::setup_agents,
            commands::fetch_stats,
            commands::detect_agents,
            commands::open_graph_cmd,
            commands::graph_url,
            commands::mark_onboarded,
            commands::is_onboarded,
            commands::start_server,
            commands::stop_server,
            commands::server_status,
        ])
        .setup(|app| {
            // Start the bundled server as a daemon (survives app closing).
            sidecar::start(app.handle().clone());

            // Always enable autostart — ormah should run at login by default.
            let _ = app.handle().autolaunch().enable();

            // Check for a desktop app update in the background — user is
            // notified and must explicitly click to install.
            updater::check(app.handle().clone());

            // Main window: shows the install/boot flow, then navigates to the
            // graph. Built in Rust so we can attach the scrollbar-hiding init
            // script that also applies after navigating to the graph.
            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("Ormah")
                    .inner_size(1180.0, 820.0)
                    .min_inner_size(860.0, 600.0)
                    .center()
                    .decorations(false) // custom dark title bar drawn in the UI
                    .initialization_script(HIDE_SCROLLBARS)
                    .initialization_script(MARK_IN_APP)
                    .build()?;

            // Hide the window on close instead of destroying it — the tray and
            // daemon keep running. User reopens via the tray icon.
            let win = window.clone();
            window.on_window_event(move |event| {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = win.hide();
                }
            });

            // Build the tray; it owns the stats poller and server controls.
            tray::build(app)?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Ormah desktop app")
        .run(|_app_handle, _event| {
            // Server is a daemon — it outlives the app process intentionally.
        });
}
