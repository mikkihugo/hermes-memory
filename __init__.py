"""Plugin entrypoint for hermes_memory."""

try:
    from .provider import HermesMemoryProvider
except ImportError:
    from provider import HermesMemoryProvider


def register(ctx) -> None:
    """Register hermes_memory as a Hermes memory provider."""
    ctx.register_memory_provider(HermesMemoryProvider())
