"""Prometheus metrics in the existing default registry.

register_metrics(registry) returns an isolated/reusable collector mapping without
rebinding REGISTRY. Module constants retain the baseline names. New adapters use
LLM_REQUESTS.labels(provider='gigachat'|'yandexgpt', status='success'|'failure'),
RAG_SCORE.observe(similarity), FALLBACK_TOTAL.labels(type='rag'|'llm'),
TICKETS_CREATED and TICKETS_FAILED. No request-specific labels are accepted.
"""

from threading import RLock

from prometheus_client import REGISTRY, Counter, Histogram, Gauge

_registration_lock = globals().get("_registration_lock", RLock())


class _BoundedCounter:
    """Reject new label values outside the documented finite domains."""

    def __init__(self, collector):
        self._collector = collector
        self._labelnames = collector._labelnames

    def __getattr__(self, name):
        return getattr(self._collector, name)

    def labels(self, *labelvalues, **labelkwargs):
        if labelvalues and labelkwargs:
            raise ValueError("use positional or keyword labels, not both")
        values = dict(zip(self._labelnames, labelvalues)) if labelvalues else labelkwargs
        if set(values) != set(self._labelnames) or len(labelvalues) not in (0, len(self._labelnames)):
            raise ValueError("invalid metric labels")
        domains = {
            "provider": {"gigachat", "yandexgpt"},
            "status": {"success", "failure"},
            "type": {"rag", "llm"},
        }
        if any(not isinstance(value, str) or value not in domains[key] for key, value in values.items()):
            raise ValueError("metric label value is outside its bounded domain")
        return self._collector.labels(*labelvalues, **labelkwargs)


def register_metrics(registry=REGISTRY) -> dict:
    """Register once per supplied registry; safe on repeated import/reload.

    Existing same-name collectors must have the expected kind/label schema;
    unrelated collectors are never unregistered. This compatibility check uses
    the prometheus client's registered-name index (there is no public lookup).
    """
    definitions = (
        ("QUERY_LATENCY", Histogram, "bot_query_latency_seconds", "Query processing time from receipt to response", ("mode",), {"buckets": [0.1, 0.5, 1, 2, 5, 10, 30, 60]}),
        ("ACTIVE_USERS", Gauge, "bot_active_users", "Number of active user sessions", (), {}),
        ("ERROR_COUNT", Counter, "bot_errors_total", "Total number of errors by type", ("error_type",), {}),
        ("LLM_REQUESTS", _BoundedCounter, "llm_requests_total", "LLM provider attempts by outcome", ("provider", "status"), {}),
        ("RAG_SCORE", Histogram, "rag_score", "Normalized RAG similarity", (), {"buckets": [0, 0.2, 0.4, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0]}),
        ("FALLBACK_TOTAL", _BoundedCounter, "fallback_total", "Fallback events by kind", ("type",), {}),
        ("TICKETS_CREATED", Counter, "tickets_created_total", "Successfully created tickets", (), {}),
        ("TICKETS_FAILED", Counter, "tickets_failed_total", "Tickets failing all delivery attempts", (), {}),
    )
    result = {}
    with _registration_lock:
        for key, kind, name, help_text, labels, options in definitions:
            bounded = kind is _BoundedCounter
            actual_kind = Counter if bounded else kind
            existing = registry._names_to_collectors.get(name)
            if existing is not None:
                expected_type = "counter" if issubclass(actual_kind, Counter) else "histogram" if kind is Histogram else "gauge"
                if existing._type != expected_type or tuple(existing._labelnames) != labels:
                    raise ValueError(f"incompatible registered metric: {name}")
                if bounded:
                    if not hasattr(existing, "_hr_bounded_facade"):
                        existing._hr_bounded_facade = _BoundedCounter(existing)
                    result[key] = existing._hr_bounded_facade
                else:
                    result[key] = existing
                continue
            collector = actual_kind(name, help_text, labels, registry=registry, **options)
            if bounded:
                collector._hr_bounded_facade = _BoundedCounter(collector)
            result[key] = collector._hr_bounded_facade if bounded else collector
    # Publish bounded zero-valued families before the first application event.
    for provider in ("gigachat", "yandexgpt"):
        for status in ("success", "failure"):
            result["LLM_REQUESTS"].labels(provider=provider, status=status)
    for event_type in ("rag", "llm"):
        result["FALLBACK_TOTAL"].labels(type=event_type)
    return result


globals().update(register_metrics())
