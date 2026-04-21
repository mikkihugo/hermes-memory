"""CLI registration for the hermes_memory provider.

## Purpose
Expose lightweight provider-local commands when hermes_memory is the active
memory plugin.
"""

from __future__ import annotations

try:
    from .config import CONFIG_FILENAME
except ImportError:
    from config import CONFIG_FILENAME


def register_cli(subparser) -> None:
    """Register the provider-local CLI surface."""
    subparser.add_argument(
        "--show-config-path",
        action="store_true",
        help="Show the profile-local config filename Hermes uses for this provider.",
    )


def hermes_memory_command(args) -> int:
    """Handle provider-local CLI actions."""
    if getattr(args, "show_config_path", False):
        print(CONFIG_FILENAME)
    return 0
