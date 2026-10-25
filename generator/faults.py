"""Fault catalog. Each fault is a failure type that starts at one service and propagates to its callers.

Template fields: {origin} the faulty service, {callee} the service this one called, {slow} a large
latency in ms, plus the generic fields from generate._fields.
"""

from dataclasses import dataclass

APP_SERVICES = ("orders-api", "payments-api", "inventory-api", "auth-service")


@dataclass(frozen=True)
class Fault:
    category: str
    origins: tuple[str, ...]  # services this fault can start at
    lead_in: tuple[tuple[str, str], ...]  # (level, template) logged once by the origin at fault start
    origin_warn: tuple[str, ...]  # quiet early-warning lines from the origin
    origin_error: tuple[str, ...]  # loud error lines from the origin
    caller_errors: tuple[str, ...]  # what direct callers log about the origin


# Used by services two or more hops away: they only know "my upstream failed".
TRANSITIVE_ERRORS: tuple[str, ...] = (
    "upstream call to {callee} failed: HTTP {status}",
    "request {id} failed after {slow}ms: {callee} returned {status}",
)
# Used by the entrypoint, where the user sees the failure.
ENTRY_ERRORS: tuple[str, ...] = (
    "GET /{path} responded {status} in {slow}ms",
    "user-facing error rendered for /{path} ({status})",
)

# Unrelated noisy errors on a service that is NOT part of the causal chain (used for `ambiguous`).
DECOY_ERRORS: tuple[str, ...] = (
    "timeout after {slow}ms calling feature-flag-service (non-critical, using defaults)",
    "failed to refresh feature flags: HTTP 429 from flag-service",
    "scheduled job cleanup_sessions exceeded 30s budget",
    "metrics exporter dropped {n} samples: buffer full",
    "failed to send audit event {id}: connection reset, will retry",
)

_FAULT_LIST = (
    Fault(
        category="db_slowdown",
        origins=("main-db",),
        lead_in=(("WARN", "lock contention detected, {n} queries waiting"),),
        origin_warn=(
            "slow query ({slow}ms): SELECT * FROM orders WHERE customer_id = {id}",
            "lock wait on relation orders exceeded {slow}ms",
        ),
        origin_error=(
            "canceling statement due to statement timeout after 30000ms",
            "deadlock detected between pid {id} and pid {n}",
        ),
        caller_errors=(
            "query timed out after {slow}ms calling {origin}",
            "database call to {origin} exceeded deadline of 5000ms",
        ),
    ),
    Fault(
        category="connection_pool_exhaustion",
        origins=("main-db",),
        lead_in=(("WARN", "connection count at 95/100"),),
        origin_warn=("connection count at {n}/100", "idle-in-transaction sessions: {n}"),
        origin_error=(
            "FATAL: sorry, too many clients already",
            "FATAL: remaining connection slots are reserved for superuser",
        ),
        caller_errors=(
            "could not acquire connection from pool: timeout after {slow}ms",
            "connection pool exhausted (active=50 idle=0) calling {origin}",
        ),
    ),
    Fault(
        category="cache_outage",
        origins=("redis-cache",),
        lead_in=(("WARN", "used memory approaching maxmemory 2048MB"),),
        origin_warn=(
            "used memory {mem}MB approaching maxmemory 2048MB",
            "evicting keys: policy allkeys-lru",
        ),
        origin_error=(
            "OOM command not allowed when used memory > 'maxmemory'",
            "client connection rejected: max clients reached",
        ),
        caller_errors=(
            "redis connection refused: {origin}:6379",
            "cache read failed after {slow}ms, falling back to database",
        ),
    ),
    Fault(
        category="memory_leak",
        origins=APP_SERVICES,
        lead_in=(("WARN", "heap usage 91% of limit, GC pause {slow}ms"),),
        origin_warn=("GC pause {slow}ms", "heap usage {n}% of limit"),
        origin_error=(
            "OutOfMemoryError: heap space exhausted",
            "container exceeded memory limit, restarting (restart count {n})",
        ),
        caller_errors=(
            "connection reset by {origin}",
            "request to {origin} failed: 503 service unavailable (restarting)",
        ),
    ),
    Fault(
        category="bad_deploy",
        origins=APP_SERVICES,
        lead_in=(("INFO", "deployment complete: version {ver} rolled out to all replicas"),),
        origin_warn=("deprecated config key 'timeout_ms' ignored, using default",),
        origin_error=(
            "unhandled exception in request handler: KeyError 'currency' (version {ver})",
            "failed to parse downstream response: unexpected schema",
        ),
        caller_errors=(
            "{origin} returned 500 for request {id}",
            "invalid response from {origin}: schema validation failed",
        ),
    ),
    Fault(
        category="queue_backlog",
        origins=("message-queue",),
        lead_in=(("WARN", "consumer lag on topic order-events: {n}000 messages"),),
        origin_warn=(
            "consumer lag on topic order-events: {n}000 messages",
            "partition {n} leader election in progress",
        ),
        origin_error=(
            "publish rejected: queue depth {n}0000 exceeds limit",
            "broker unavailable: replication lag {slow}ms",
        ),
        caller_errors=(
            "publish to {origin} timed out after {slow}ms",
            "failed to enqueue event {id}: broker not available",
        ),
    ),
    Fault(
        category="cert_expiry",
        origins=("auth-service", "payments-api", "inventory-api"),
        lead_in=(("WARN", "TLS certificate CN={origin}.internal expired, renewal job has not run"),),
        origin_warn=(
            "TLS certificate CN={origin}.internal is expired",
            "inbound handshake failed from {n} clients",
        ),
        origin_error=(
            "tls: expired certificate, rejecting connection from 10.0.{n}.{fast}",
            "handshake error: certificate verification failed",
        ),
        caller_errors=(
            "x509: certificate has expired or is not yet valid calling {origin}",
            "TLS handshake failed with {origin}: certificate verify failed",
        ),
    ),
    Fault(
        category="disk_full",
        origins=("main-db", "message-queue"),
        lead_in=(("WARN", "disk usage at 97% on /var/lib/data"),),
        origin_warn=("disk usage at {pct}% on /var/lib/data",),
        origin_error=(
            "PANIC: could not write to file: No space left on device",
            "write failed: no space left on device",
        ),
        caller_errors=(
            "write to {origin} rejected: insufficient storage",
            "{origin} unavailable: read-only mode",
        ),
    ),
)

FAULTS: dict[str, Fault] = {f.category: f for f in _FAULT_LIST}
