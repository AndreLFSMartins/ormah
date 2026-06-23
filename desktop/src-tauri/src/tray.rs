//! The menubar tray: icon + title (weekly counter) + dropdown menu.

use tauri::{
    menu::{CheckMenuItemBuilder, MenuBuilder, MenuItemBuilder},
    tray::TrayIconBuilder,
    App, Manager,
};
use tauri_plugin_autostart::ManagerExt;

use crate::{commands, stats};

pub fn build(app: &App) -> tauri::Result<()> {
    let handle = app.handle();

    // Stats lines (disabled = display-only). Updated live by the poller.
    let stats_week = MenuItemBuilder::with_id("stats_week", "Whispers used: …")
        .enabled(false)
        .build(app)?;
    let stats_total = MenuItemBuilder::with_id("stats_total", " ")
        .enabled(false)
        .build(app)?;

    let open_graph = MenuItemBuilder::with_id("open_graph", "Open graph").build(app)?;
    let setup = MenuItemBuilder::with_id("setup", "Set up agent…").build(app)?;

    let autostart_on = handle.autolaunch().is_enabled().unwrap_or(false);
    let start_login = CheckMenuItemBuilder::with_id("start_login", "Start at login")
        .checked(autostart_on)
        .build(app)?;

    let quit = MenuItemBuilder::with_id("quit", "Quit Ormah").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&stats_week)
        .item(&stats_total)
        .separator()
        .item(&open_graph)
        .item(&setup)
        .item(&start_login)
        .separator()
        .item(&quit)
        .build()?;

    // Clone the check item so the event handler can flip its checkmark.
    let start_login_for_event = start_login.clone();

    let tray = TrayIconBuilder::with_id("ormah-tray")
        .icon(tauri::include_image!("icons/icon.png"))
        .icon_as_template(true)
        .title("…")
        .tooltip("Ormah")
        .menu(&menu)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "open_graph" => commands::open_graph(app),
            "setup" => commands::run_setup_notify(app.clone()),
            "start_login" => {
                let am = app.autolaunch();
                let now_on = am.is_enabled().unwrap_or(false);
                let _ = if now_on { am.disable() } else { am.enable() };
                let _ = start_login_for_event.set_checked(!now_on);
            }
            "quit" => {
                crate::sidecar::stop();
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    // Poll /agent/stats and push the numbers into the tray title + menu lines.
    stats::spawn_poller(handle.clone(), tray, stats_week, stats_total);

    Ok(())
}
