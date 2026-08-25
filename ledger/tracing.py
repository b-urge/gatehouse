"""[otel] -> Cloud Trace (GEAP-AUDIT row 7): content-free ledger spans.

pollard's OpenTelemetry bridge emits one span per node carrying only ids and
digests — node id, parent id, result digest, registry digest, charges, refusal
reason — never a payload, query, or document. Two entry points:

  ledger_span_hook()           Runtime.on_node callback: a span the instant a
                               node is recorded, nested under whatever span is
                               current (on Agent Engine: ADK's execute_tool span,
                               so Cloud Trace shows fleet -> tool -> ledger node).
  export_run(store, root_id)   after the fact: one correctly parented tree.

Provider policy: library code never installs a TracerProvider. On Agent Engine
ADK's --otel_to_cloud owns the global provider (Cloud Trace + Cloud Logging) and
`trace.get_tracer` joins it; with no provider, spans are no-ops. `local_tracing`
installs a console or in-memory exporter for seeing and asserting spans offline.

opentelemetry is imported lazily: CI installs neither it nor ADK.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from pollard import Node, Store

TRACER_NAME = "gatehouse.ledger"


def enabled() -> bool:
    """Spans are on unless GATEHOUSE_LEDGER_TRACE=0 or opentelemetry is absent."""
    if os.environ.get("GATEHOUSE_LEDGER_TRACE", "1") == "0":
        return False
    try:
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


def tracer() -> Any:
    from opentelemetry import trace

    return trace.get_tracer(TRACER_NAME)


def ledger_span_hook(otel_tracer: Any | None = None) -> Callable[[Node], None] | None:
    """The Runtime.on_node callback, or None when tracing is off/unavailable."""
    if otel_tracer is None and not enabled():
        return None
    from pollard.otel import live_span_hook

    return live_span_hook(otel_tracer or tracer())


def export_run(store: Store, root_id: str, otel_tracer: Any | None = None) -> int:
    """Re-export one recorded run as a parented span tree; returns the span count."""
    from pollard.otel import export_spans

    return export_spans(store, root_id, otel_tracer or tracer())


def local_tracing(exporter: str = "console") -> Any:
    """Install a local TracerProvider (once) with a console or in-memory exporter
    and return the exporter. For demos and tests; never called on Agent Engine."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": "gatehouse-ledger"}))
        trace.set_tracer_provider(provider)
    span_exporter = ConsoleSpanExporter() if exporter == "console" else InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return span_exporter
