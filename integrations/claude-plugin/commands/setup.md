---
description: Install or repair the local Ormah runtime required by this plugin.
---

Set up the local Ormah runtime for this plugin.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If it is missing, explain that this plugin needs the local Ormah runtime and
   ask permission to run:
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
7. Verify that setup succeeded with:
   `ormah server status`
8. If the server is healthy, install the shared Ormah guidance block into the
   Claude memory file that matches this plugin's install scope so Claude
   follows the same recall, remember, outdated, and maintenance workflow as the
   standard Ormah install. Ask permission before running:
   `ormah claude-md install`
   This writes to `~/.claude/CLAUDE.md` for user-scoped plugin installs,
   `./CLAUDE.md` for project-scoped installs, and `./CLAUDE.local.md` for
   local-scoped installs.
9. If guidance installation succeeds, tell the user the plugin is ready and
   point them to `http://localhost:8787`.
10. If any step fails, stop and summarize the exact failure plus the next manual
   recovery command.

Important:

- Do not treat `ormah setup --update` as equivalent to `--skip-client-setup`;
  `--update` can reapply global Claude/Codex/Desktop wiring.
- Use `/ormah:upgrade` for plugin-safe runtime upgrades.
- Do not run `ormah setup` without `--skip-client-setup` in this workflow.
- Use `ormah claude-md install` to write the shared Ormah guidance block to the
  CLAUDE.md file that matches the plugin install scope.
- Do not silently install or upgrade software; ask before running shell
  commands that change the system.
