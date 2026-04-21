"""Install helpers for the hermes_memory plugin.

## Purpose
Provide a deterministic local install path for the standalone provider repo so
Hermes can discover it under `$HERMES_HOME/plugins/hermes_memory`.
"""

from __future__ import annotations

import shutil
from pathlib import Path


PLUGIN_DIRECTORY_NAME = "hermes_memory"
PLUGINS_DIRECTORY_NAME = "plugins"


def resolve_install_path(hermes_home: str | Path) -> Path:
    """Return the canonical Hermes plugin install path."""
    return Path(hermes_home) / PLUGINS_DIRECTORY_NAME / PLUGIN_DIRECTORY_NAME


def install_plugin(source_directory: str | Path, hermes_home: str | Path, *, symlink: bool = True) -> Path:
    """Install the plugin into `$HERMES_HOME/plugins/hermes_memory`.

    Args:
        source_directory: Standalone plugin repo directory.
        hermes_home: Hermes home directory.
        symlink: When true, install as a symlink for editable development.

    Returns:
        The installed plugin path.
    """
    source_path = Path(source_directory).resolve()
    install_path = resolve_install_path(hermes_home)
    install_path.parent.mkdir(parents=True, exist_ok=True)

    if install_path.is_symlink() or install_path.exists():
        if install_path.is_symlink() or install_path.is_file():
            install_path.unlink()
        else:
            shutil.rmtree(install_path)

    if symlink:
        install_path.symlink_to(source_path, target_is_directory=True)
        return install_path

    shutil.copytree(source_path, install_path)
    return install_path
