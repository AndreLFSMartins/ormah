# Ormah Plugin Setup

This plugin depends on the local Ormah runtime. Follow this playbook whenever the
plugin is installed, enabled, or looks disconnected.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If `ormah` is missing, explain that the plugin needs the local Ormah runtime
   and ask permission to run:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
3. After the binary is available, run:
   `ormah setup --skip-client-setup`
4. Verify that the local runtime is healthy with:
   `ormah server status`
5. If the server is healthy, tell the user the plugin is ready and mention the
   graph UI at `http://localhost:8787`.
6. If any step fails, stop, summarize the exact error, and give the next manual
   command to recover.

Important:

- Do not run `ormah setup` without `--skip-client-setup` in this plugin flow.
- Do not silently install software; ask before running shell commands that
  change the system.
