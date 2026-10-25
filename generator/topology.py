"""Service topology: who calls whom, and what a healthy service logs.

Message templates are str.format templates; the fields are filled in by generate._fields.
"""

from dataclasses import dataclass

# service -> the services it calls
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "frontend": ("api-gateway",),
    "api-gateway": ("auth-service", "orders-api", "payments-api", "inventory-api"),
    "auth-service": ("redis-cache",),
    "orders-api": ("main-db", "inventory-api", "message-queue"),
    "payments-api": ("main-db", "message-queue"),
    "inventory-api": ("redis-cache", "main-db"),
    "main-db": (),
    "redis-cache": (),
    "message-queue": (),
}

# The service users hit first. Its errors are the "loudest symptom" in most incidents.
ENTRYPOINT = "frontend"


@dataclass(frozen=True)
class HealthyProfile:
    info_per_min: int
    info: tuple[str, ...]


HEALTHY: dict[str, HealthyProfile] = {
    "frontend": HealthyProfile(
        25,
        (
            "GET /{path} 200 {ms}ms",
            "GET /static/app.{id}.js 304 {ms}ms",
            "session {id} started",
        ),
    ),
    "api-gateway": HealthyProfile(
        25,
        (
            "routed GET /{path} to upstream in {ms}ms",
            "request {id} authorized",
            "POST /api/{path} 200 {ms}ms",
        ),
    ),
    "auth-service": HealthyProfile(
        15,
        (
            "token issued for user {id}",
            "token validated in {ms}ms",
            "session {id} refreshed",
        ),
    ),
    "orders-api": HealthyProfile(
        15,
        (
            "order {id} created for customer {n}",
            "GET /orders/{id} 200 {ms}ms",
            "order {id} status updated to shipped",
        ),
    ),
    "payments-api": HealthyProfile(
        12,
        (
            "payment {id} authorized amount={n}.00 USD",
            "payment {id} captured in {ms}ms",
            "refund {id} processed",
        ),
    ),
    "inventory-api": HealthyProfile(
        12,
        (
            "stock check for sku-{id} ok",
            "reserved {n} units of sku-{id}",
            "GET /inventory/{id} 200 {ms}ms",
        ),
    ),
    "main-db": HealthyProfile(
        20,
        (
            "duration: {fast} ms execute: SELECT id FROM orders WHERE id = {id}",
            "checkpoint complete: wrote {n} buffers",
            "autovacuum: processed table public.orders",
        ),
    ),
    "redis-cache": HealthyProfile(
        20,
        (
            "GET session:{id} hit",
            "SET cart:{id} ok",
            "used_memory={n}MB keys={id}",
        ),
    ),
    "message-queue": HealthyProfile(
        10,
        (
            "message published to topic order-events offset={id}",
            "consumer group billing committed offset {id}",
            "topic order-events partitions healthy",
        ),
    ),
}

# Benign background noise every service emits, so error counts are never zero in a healthy system.
BASE_WARNS: tuple[str, ...] = (
    "request took {ms}ms (threshold 500ms)",
    "retrying request attempt 1/3 after transient error",
)
BASE_ERRORS: tuple[str, ...] = (
    "request {id} rejected: validation failed (missing field)",
    "client closed connection before response was sent",
)


def callers_by_depth(service: str) -> list[list[str]]:
    """Transitive callers of `service`, grouped by distance. Depth 1 = direct callers."""
    levels: list[list[str]] = []
    seen = {service}
    frontier = [service]
    while True:
        callers = [
            s
            for s, deps in DEPENDENCIES.items()
            if s not in seen and any(d in frontier for d in deps)
        ]
        if not callers:
            return levels
        levels.append(callers)
        seen.update(callers)
        frontier = callers
