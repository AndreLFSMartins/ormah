# Ormah Claude Plugin

This directory contains the in-repo Claude Code plugin for Ormah.

## What it bundles

- Claude plugin manifest
- Plugin-scoped hook configuration for whisper inject/store
- Plugin-scoped MCP registration for `ormah mcp`
- A setup playbook and explicit `/ormah:setup`, `/ormah:status`, and
  `/ormah:upgrade` commands
- The Ormah maintenance agent

## What it does not bundle

This plugin does not ship the Ormah runtime itself. Users still need the local
`ormah` CLI and background server on their machine. The plugin guides Claude
through installing and configuring that runtime.

## Local development

Run Claude Code against the local plugin directory:

```bash
claude --plugin-dir ./integrations/claude-plugin
```

Useful commands once Claude starts:

- `/ormah:setup`
- `/ormah:status`
- `/ormah:upgrade`
- `/reload-plugins`

Maintenance does not need a dedicated slash command in plugin mode. The plugin
keeps the `ormah-maintenance` agent available, and Ormah can trigger it
automatically when maintenance is due.

## Setup flow

The intended first-run flow is:

1. Install or enable the plugin
2. Run `/ormah:setup`
3. If `ormah` is missing, install it with:
   `bash <(curl -fsSL https://ormah.me/install.sh) --no-setup`
4. If the installed runtime does not support `ormah setup --skip-client-setup`,
   run `/ormah:upgrade`
5. Configure the local runtime with:
   `ormah setup --skip-client-setup`
6. Let the plugin own Claude-side hooks and MCP wiring

The plugin should never substitute `ormah setup --update` for plugin mode;
`--update` can reapply global client wiring outside the plugin.
