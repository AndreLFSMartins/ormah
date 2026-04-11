# Ormah Plugin Setup

This plugin depends on the local Ormah runtime. Follow this playbook whenever the
plugin is installed, enabled, or looks disconnected.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If `ormah` is missing, explain that the plugin needs the local Ormah runtime
   and ask permission to run:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
3. If `ormah` is present, report the installed version with:
   `ormah --version`
4. Check whether the installed runtime supports plugin-safe setup with:
   `ormah setup --help`
5. If the help output includes `--skip-client-setup`, run:
   `ormah setup --skip-client-setup`
6. If the help output does not include `--skip-client-setup`, explain that the
   installed runtime is too old for plugin mode and recommend running
   `/ormah:upgrade`.
7. Verify that the local runtime is healthy with:
   `ormah server status`
8. If the server is healthy, tell the user the plugin is ready and mention the
   graph UI at `http://localhost:8787`.
9. If any step fails, stop, summarize the exact error, and give the next manual
   command to recover.

Important:

- Do not treat `ormah setup --update` as equivalent to `--skip-client-setup`;
  `--update` can reapply global Claude/Codex/Desktop wiring.
- Use `/ormah:upgrade` for plugin-safe runtime upgrades.
- Do not run `ormah setup` without `--skip-client-setup` in this plugin flow.
- Do not silently install or upgrade software; ask before running shell
  commands that change the system.
