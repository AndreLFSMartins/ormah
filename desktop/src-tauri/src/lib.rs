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
            commands::open_graph_cmd,
            commands::mark_onboarded,
            commands::is_onboarded,
        ])
        .setup(|app| {
            // Start the bundled server the moment the app launches.
            sidecar::start(app.handle().clone());

            // Build the menubar tray; it owns the stats poller.
            tray::build(app)?;

            // First run: no onboarding marker yet → show the onboarding window.
            if !commands::onboarded(app.handle()) {
                commands::open_onboarding(app.handle())?;
            }

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
