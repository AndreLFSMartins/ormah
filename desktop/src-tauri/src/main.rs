// Prevent an extra console window on Windows in release. No-op on macOS, but
// kept so a future cross-platform target doesn't regress.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ormah_desktop_lib::run();
}
