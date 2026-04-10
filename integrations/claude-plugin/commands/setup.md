---
description: Install or repair the local Ormah runtime required by this plugin.
---

Set up the local Ormah runtime for this plugin.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If it is missing, explain that this plugin needs the local Ormah runtime and
   ask permission to run:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
3. After the binary is available, run:
   `ormah setup --skip-client-setup`
4. Verify that setup succeeded with:
   `ormah server status`
5. If the server is healthy, tell the user the plugin is ready and point them to
   `http://localhost:8787`.
6. If any step fails, stop and summarize the exact failure plus the next manual
   recovery command.

Important:

- Do not run `ormah setup` without `--skip-client-setup` in this workflow.
- Do not silently install software; ask before running shell commands that
  change the system.
