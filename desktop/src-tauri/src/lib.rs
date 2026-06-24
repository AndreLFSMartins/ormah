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

use tauri_plugin_autostart::MacosLauncher;

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
        ])
        .setup(|app| {
            // Start the bundled server the moment the app launches. The main
            // window (declared in tauri.conf.json) shows the install/boot flow
            // and then loads the graph from the local server.
            sidecar::start(app.handle().clone());

            // Build the tray; it owns the stats poller and a quick "Open graph".
            tray::build(app)?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Ormah desktop app")
        .run(|_app_handle, event| {
            // Make sure the bundled server dies with the app.
            if let tauri::RunEvent::Exit = event {
                sidecar::stop();
            }
        });
}
