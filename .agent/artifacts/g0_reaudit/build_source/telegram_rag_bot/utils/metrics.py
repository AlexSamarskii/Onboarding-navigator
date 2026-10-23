"""
Prometheus metrics definitions for bot monitoring.

Metrics:
- bot_query_latency_seconds: Query processing time (Histogram)
- bot_active_users: Active user sessions (Gauge)
- bot_errors_total: Total errors by type (Counter)
"""

from prometheus_client import Counter, Histogram, Gauge

# Query latency metric (Histogram)
QUERY_LATENCY = Histogram(
    "bot_query_latency_seconds",
    "Query processing time from receipt to response",
    ["mode"],
    buckets=[
        0.1,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
        30.0,
        60.0,
    ],  # Buckets for latency distribution
)

# Active users metric (Gauge)
ACTIVE_USERS = Gauge("bot_active_users", "Number of active user sessions")

# Error count metric (Counter)
ERROR_COUNT = Counter(
    "bot_errors_total", "Total number of errors by type", ["error_type"]
)

# Note: TOKEN_USAGE metric отложен на Week 2 (требует state management для cumulative metrics)
