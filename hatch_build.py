"""Hatch build hook — keeps the bundled UI current for packaged releases."""

import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _iter_ui_source_files(ui_dir: Path):
    for rel_path in ("package.json", "package-lock.json", "vite.config.ts"):
        path = ui_dir / rel_path
        if path.is_file():
            yield path

    for pattern in ("tsconfig*.json", "src/**/*", "public/**/*"):
        for path in ui_dir.glob(pattern):
            if path.is_file():
                yield path


def _ui_needs_rebuild(ui_dir: Path, ui_dist: Path) -> bool:
    index_html = ui_dist / "index.html"
    if not index_html.exists():
        return True

    dist_mtime = index_html.stat().st_mtime
    return any(path.stat().st_mtime > dist_mtime for path in _iter_ui_source_files(ui_dir))


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        ui_dir = Path("ui")
        ui_dist = Path("src/ormah/ui_dist")

        # No UI source — nothing to build
        if not (ui_dir / "package.json").exists():
            return

        needs_build = _ui_needs_rebuild(ui_dir, ui_dist)
        if not needs_build:
            return

        # npm not available — skip silently
        npm = shutil.which("npm")
        if not npm:
            if (ui_dist / "index.html").exists():
                self.app.display_warning(
                    "npm not found — reusing existing src/ormah/ui_dist even though UI sources "
                    "appear newer."
                )
            else:
                self.app.display_warning(
                    "npm not found — skipping UI build. "
                    "The server will work but the graph UI won't be available."
                )
            return

        self.app.display_info("Building UI...")
        install_cmd = [npm, "ci"] if (ui_dir / "package-lock.json").exists() else [npm, "install"]
        subprocess.run(install_cmd, cwd="ui", check=True, capture_output=True)
        subprocess.run([npm, "run", "build"], cwd="ui", check=True, capture_output=True)
        self.app.display_info("UI built successfully.")
