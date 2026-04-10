---
description: Check whether the local Ormah runtime required by this plugin is installed and healthy.
---

Check the current Ormah runtime status for this plugin.

1. Check whether `ormah` is installed with `command -v ormah`.
2. If `ormah` is missing, tell the user the local runtime is not installed and
   recommend running `/ormah:setup`.
3. If `ormah` is present, report the installed version with:
   `ormah --version`
4. Then run:
   `ormah server status`
5. Report one of these states clearly:
   - Ormah installed and server running
   - Ormah installed but server not running
   - Ormah not installed
6. If the server is running, mention the graph UI at `http://localhost:8787`.
7. If the server is not running, recommend `/ormah:setup`.
