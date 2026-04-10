---
description: Check whether the local Ormah runtime required by this plugin is installed and healthy.
---

Check the current Ormah runtime status for this plugin.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If `ormah` is missing, tell the user the local runtime is not installed and
   recommend running `/ormah:setup`.
3. If `ormah` is present, run:
   `ormah server status`
4. Report one of these states clearly:
   - Ormah installed and server running
   - Ormah installed but server not running
   - Ormah not installed
5. If the server is running, mention the graph UI at `http://localhost:8787`.
6. If the server is not running, recommend `/ormah:setup`.
