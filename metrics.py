"""Provider metrics for hermes_memory.

## Purpose
Track provider-local operation counts, failures, and latencies so Hermes can
inspect memory-provider health without external observability dependencies.
"""

from __future__ import annotations

from threading import Lock
from time import monotonic

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default
    def field_validator(*args, **kwargs):
        return lambda f: f


class OperationMetrics(BaseModel):
    """Aggregate metrics for one provider operation with validation."""

    count: int = Field(default=0, ge=0, description="Total operation count")
    failure_count: int = Field(default=0, ge=0, description="Failed operation count")
    total_duration_seconds: float = Field(default=0.0, ge=0.0, description="Total duration")

    @field_validator("failure_count")
    @classmethod
    def validate_failure_count(cls, v: int, info) -> int:
        """Ensure failure_count <= count."""
        if hasattr(info, 'data') and 'count' in info.data:
            count = info.data['count']
            if v > count:
                raise ValueError(f"failure_count ({v}) cannot exceed count ({count})")
        return v

    @property
    def average_duration_seconds(self) -> float:
        """Return the average successful-or-failed duration."""
        if self.count == 0:
            return 0.0
        return self.total_duration_seconds / self.count

    class Config:
        """Pydantic config."""
        validate_assignment = True


class ProviderMetricsSnapshot(BaseModel):
    """Serializable provider metrics snapshot with validation."""

    operations: dict[str, OperationMetrics] = Field(
        default_factory=dict,
        description="Metrics by operation name"
    )

    def to_payload(self) -> dict[str, dict[str, float | int]]:
        """Return a JSON-serializable payload."""
        payload: dict[str, dict[str, float | int]] = {}
        for operation_name, metrics in self.operations.items():
            if hasattr(metrics, 'model_dump'):
                operation_payload = metrics.model_dump()
            elif hasattr(metrics, 'dict'):
                operation_payload = metrics.dict()
            else:
                from dataclasses import asdict
                operation_payload = asdict(metrics)
            operation_payload["average_duration_seconds"] = metrics.average_duration_seconds
            payload[operation_name] = operation_payload
        return payload

    class Config:
        """Pydantic config."""
        validate_assignment = True


class ProviderMetricsCollector:
    """Thread-safe in-memory metrics collector."""

    def __init__(self) -> None:
        self._metrics_by_operation: dict[str, OperationMetrics] = {}
        self._lock = Lock()

    def start_operation(self) -> float:
        """Return a monotonic timestamp used to measure one operation."""
        return monotonic()

    def record_success(self, operation_name: str, started_at: float) -> None:
        """Record a successful operation timing sample."""
        self._record(operation_name=operation_name, started_at=started_at, failed=False)

    def record_failure(self, operation_name: str, started_at: float) -> None:
        """Record a failed operation timing sample."""
        self._record(operation_name=operation_name, started_at=started_at, failed=True)

    def snapshot(self) -> ProviderMetricsSnapshot:
        """Return the current metrics snapshot."""
        with self._lock:
            snapshot_operations = {
                operation_name: OperationMetrics(
                    count=metrics.count,
                    failure_count=metrics.failure_count,
                    total_duration_seconds=metrics.total_duration_seconds,
                )
                for operation_name, metrics in self._metrics_by_operation.items()
            }
        return ProviderMetricsSnapshot(operations=snapshot_operations)

    def _record(self, operation_name: str, started_at: float, failed: bool) -> None:
        """Record one operation sample."""
        elapsed_seconds = max(monotonic() - started_at, 0.0)
        with self._lock:
            metrics = self._metrics_by_operation.setdefault(operation_name, OperationMetrics())
            metrics.count += 1
            metrics.total_duration_seconds += elapsed_seconds
            if failed:
                metrics.failure_count += 1
