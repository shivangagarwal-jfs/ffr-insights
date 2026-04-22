"""OpenTelemetry tracing setup for FFR API.

Provides ``init_tracing()`` to bootstrap the TracerProvider + exporter, a
module-level ``get_tracer()`` helper, and a ``@traced`` decorator that wraps
any function in a span with optional static attributes.

Configuration (read from ``config.yaml`` / env at init time):
    tracing_enabled        – bool, default True
    tracing_exporter       – "console" | "otlp", default "console"
    tracing_service_name   – str,  default "ffr-api"
    otlp_endpoint          – str,  required when exporter == "otlp"
"""

from __future__ import annotations

import atexit
import functools
import os
from typing import Any, Callable, TypeVar

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import StatusCode

F = TypeVar("F", bound=Callable[..., Any])

_TRACER_NAME = "ffr-api"
_initialized = False
_provider: TracerProvider | None = None


def init_tracing(config: dict[str, Any] | None = None) -> None:
    """Bootstrap the OTel TracerProvider once.  Safe to call multiple times."""
    global _initialized, _provider
    if _initialized:
        return

    cfg = config or {}
    enabled = _bool_from(cfg.get("tracing_enabled"), default=True)
    if not enabled:
        _initialized = True
        return

    service_name = str(cfg.get("tracing_service_name") or os.environ.get("OTEL_SERVICE_NAME") or "ffr-api")
    exporter_kind = str(cfg.get("tracing_exporter", "console")).lower()

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if exporter_kind == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        except ImportError as exc:
            raise ImportError(
                "Install 'opentelemetry-exporter-otlp-proto-grpc' for OTLP export."
            ) from exc
        endpoint = str(
            cfg.get("otlp_endpoint")
            or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or "http://localhost:4317"
        )
        insecure = endpoint.startswith("http://")
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
        )
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _provider = provider
    atexit.register(_shutdown_provider)
    _initialized = True


def _shutdown_provider() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()


def shutdown_tracing() -> None:
    """Flush and shut down the TracerProvider (call from app shutdown hook)."""
    _shutdown_provider()


def get_tracer(name: str | None = None) -> trace.Tracer:
    return trace.get_tracer(name or _TRACER_NAME)


def current_otel_context() -> otel_context.Context:
    """Snapshot the current OTel context (for cross-thread propagation)."""
    return otel_context.get_current()


def attach_context(ctx: otel_context.Context) -> object:
    """Attach a previously captured context in the current thread."""
    return otel_context.attach(ctx)


def detach_context(token: object) -> None:
    otel_context.detach(token)  # type: ignore[arg-type]


def traced(
    span_name: str | None = None,
    *,
    attributes: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorator that wraps a function in an OTel span.

    Usage::

        @traced("my_operation", attributes={"component": "pipeline"})
        def do_work(x, y): ...
    """

    def decorator(fn: F) -> F:
        name = span_name or fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(fn.__module__)
            with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
                try:
                    result = fn(*args, **kwargs)
                    return result
                except Exception as exc:
                    span.set_status(StatusCode.ERROR, str(exc))
                    span.record_exception(exc)
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator


def _bool_from(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes")
