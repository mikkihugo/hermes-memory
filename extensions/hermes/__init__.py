"""Plugin entrypoint for singularity_memory."""

try:
    from .provider import SingularityMemoryProvider
except ImportError:
    from provider import SingularityMemoryProvider


def register(ctx) -> None:
    """Register singularity_memory as a Hermes memory provider."""
    ctx.register_memory_provider(SingularityMemoryProvider())
