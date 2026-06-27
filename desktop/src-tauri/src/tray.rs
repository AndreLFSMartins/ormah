//! The menubar tray: icon + title (weekly counter) + dropdown menu.

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, Listener,
};
use tauri_plugin_autostart::ManagerExt;

use crate::{commands, stats, updater};

fn login_label(enabled: bool) -> &'static str {
    if enabled { "Start at login  ✓" } else { "Start at login" }
}

pub fn build(app: &App) -> tauri::Result<()> {
    let handle = app.handle();

    // Stats lines (disabled = display-only). Updated live by the poller.
    let stats_week = MenuItemBuilder::with_id("stats_week", "…")
        .enabled(false)
        .build(app)?;
    let stats_total = MenuItemBuilder::with_id("stats_total", " ")
        .enabled(false)
        .build(app)?;

    // Shown only when a new version is available; enabled on that event.
    let update_item = MenuItemBuilder::with_id("install_update", "Update available…")
        .enabled(false)
        .build(app)?;

    let open_graph = MenuItemBuilder::with_id("open_graph", "Open Ormah").build(app)?;

    let autostart_on = handle.autolaunch().is_enabled().unwrap_or(false);
    let start_login =
        MenuItemBuilder::with_id("start_login", login_label(autostart_on)).build(app)?;

    let quit = MenuItemBuilder::with_id("quit", "Quit Ormah").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&stats_week)
        .item(&stats_total)
        .separator()
        .item(&update_item)
        .item(&open_graph)
        .item(&start_login)
        .separator()
        .item(&quit)
        .build()?;

    // Activate the update item with version label when notified.
    let update_item_for_event = update_item.clone();
    handle.listen("ormah://update-available", move |event| {
        if let Ok(payload) = serde_json::from_str::<updater::UpdateAvailable>(event.payload()) {
            let label = format!("Install update {}…", payload.version);
            let _ = update_item_for_event.set_text(label);
            let _ = update_item_for_event.set_enabled(true);
        }
    });

    let start_login_for_event = start_login.clone();

    let tray = TrayIconBuilder::with_id("ormah-tray")
        .icon(tauri::include_image!("icons/icon.png"))
        .icon_as_template(false)
        .title("…")
        .tooltip("Ormah — click to open")
        .menu(&menu)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "install_update" => updater::install(app.clone()),
            "open_graph" => commands::open_graph(app),
            "start_login" => {
                let am = app.autolaunch();
                let now_on = am.is_enabled().unwrap_or(false);
                let _ = if now_on { am.disable() } else { am.enable() };
                let _ = start_login_for_event.set_text(login_label(!now_on));
            }
            "quit" => {
                crate::sidecar::stop();
                app.exit(0);
            }
            _ => {}
        })
        // Left-click opens the graph; right-click (or platform default) shows menu.
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                commands::open_graph(tray.app_handle());
            }
        })
        .build(app)?;

    // Poll /agent/stats and push the numbers into the tray title + menu lines.
    stats::spawn_poller(handle.clone(), tray, stats_week, stats_total);

    Ok(())
}
