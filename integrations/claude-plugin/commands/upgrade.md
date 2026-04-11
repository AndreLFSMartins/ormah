---
description: Upgrade the local Ormah runtime required by this plugin without reapplying global client wiring.
---

Upgrade the local Ormah runtime for this plugin.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If `ormah` is missing, explain that the plugin needs the local Ormah runtime
   and ask permission to run:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
3. If `ormah` is present, report the installed version with:
   `ormah --version`
4. Ask permission to run the plugin-safe upgrade command:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
5. After the upgrade, re-check the installed version with:
   `ormah --version`
6. Then check whether the upgraded runtime supports plugin-safe setup with:
   `ormah setup --help`
7. If the help output includes `--skip-client-setup`, tell the user the upgrade
   succeeded and recommend running `/ormah:setup` next.
8. If the help output still does not include `--skip-client-setup`, stop and
   explain that the published runtime still does not support plugin mode yet.
9. If any step fails, stop and summarize the exact failure plus the next manual
   recovery command.

Important:

- Use `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup` for plugin
  upgrades. Do not substitute `ormah setup --update`.
- Do not silently install or upgrade software; ask before running shell
  commands that change the system.
