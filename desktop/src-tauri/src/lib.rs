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
#[cfg(target_os = "linux")]
use tauri::Manager;
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

/// Linux single-instance guard.
///
/// macOS uses `tauri-plugin-single-instance` (a Unix socket). On Linux that
/// plugin instead claims a D-Bus well-known name, which fails silently in the
/// AppImage/deb runtime and lets duplicate instances — and duplicate tray
/// icons — through. Here we reserve a per-user *abstract* Unix socket: the
/// kernel guarantees a single owner and auto-releases it when the process
/// dies, so there are no stale lock files.
///
/// Returns `Ok(Some(listener))` when we are the first instance (the caller
/// must keep the listener alive for the process lifetime), `Ok(None)` for a
/// duplicate that should exit, and `Err` when the mechanism is unavailable —
/// in which case the caller boots anyway, since failing open must never block
/// the app from starting.
#[cfg(target_os = "linux")]
fn single_instance_listener() -> std::io::Result<Option<std::os::unix::net::UnixListener>> {
    use std::os::linux::net::SocketAddrExt;
    use std::os::unix::net::{SocketAddr, UnixListener};

    // XDG_RUNTIME_DIR is already per-user (/run/user/<uid>), so embedding it
    // scopes the lock to this user without having to look up the uid.
    let scope = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "shared".into());
    let name = format!("ormah-desktop.{}", scope.replace('/', "_"));
    let addr = SocketAddr::from_abstract_name(name.as_bytes())?;
    match UnixListener::bind_addr(&addr) {
        Ok(listener) => Ok(Some(listener)),
        Err(e) if e.kind() == std::io::ErrorKind::AddrInUse => Ok(None),
        Err(e) => Err(e),
    }
}

pub fn run() {
    #[allow(unused_mut)]
    let mut builder = tauri::Builder::default();

    // macOS/other: the plugin handles single-instance and focuses the existing
    // window on a second launch. Linux uses the abstract-socket guard in
    // `setup` instead (see `single_instance_listener`).
    #[cfg(not(target_os = "linux"))]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            commands::open_graph(app);
        }));
    }

    builder
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
            // Linux: refuse to start a second instance so we never spawn a
            // duplicate tray icon. macOS handles this via the plugin above.
            #[cfg(target_os = "linux")]
            match single_instance_listener() {
                // Another instance already owns the lock — exit before building
                // anything. (Focusing its window would require IPC; skipped.)
                Ok(None) => std::process::exit(0),
                // First instance: hold the socket for the whole process life.
                Ok(Some(listener)) => {
                    app.manage(listener);
                }
                // Mechanism unavailable — boot anyway rather than block startup.
                Err(e) => eprintln!("single-instance guard unavailable, continuing: {e}"),
            }

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
