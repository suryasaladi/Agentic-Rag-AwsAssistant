# Monitoring & Alerts Runbook

Owner: SRE Team
Last reviewed: 2026-06-05

## The four golden signals

Every service dashboard tracks:
- **Latency** — p50, p95, p99 response times
- **Traffic** — requests per second
- **Errors** — 4xx and 5xx rate
- **Saturation** — CPU, memory, connection pool, queue depth

## Standard alert thresholds

| Alert | Condition | Severity |
|-------|-----------|----------|
| High error rate | 5xx > 1% for 5 min | SEV2 |
| Elevated latency | p99 > 800 ms for 10 min | SEV3 |
| Service down | health check failing on all replicas | SEV1 |
| CPU saturation | CPU > 85% for 10 min | SEV3 |
| Disk pressure | disk usage > 85% | SEV3 |
| Certificate expiry | TLS cert expires in < 14 days | SEV3 |

## Responding to a "High error rate" alert

1. Open the service dashboard; confirm the error rate and identify which endpoints.
2. Check the deploy timeline — did errors start right after a deploy? If so, see
   the Deployment & Rollback runbook and roll back.
3. Check dependencies (database, downstream APIs) for correlated failures.
4. If a single bad host, cordon it: `opsctl node cordon <node>`.
5. If widespread and tied to a release, roll back. If tied to a dependency,
   consider load shedding.

## Silencing and escalation

- Silence a **known, tracked** alert during a maintenance window only:
  `opsctl alert silence --name <alert> --duration 1h --reason "<ticket>"`.
- Never silence an alert without a linked ticket.
- An alert that pages twice in a week for the same non-actionable reason is a bug —
  file it to tune the threshold rather than muting it.

## Logs and tracing

- Structured logs are searchable in the logging platform; filter by
  `service`, `trace_id`, and `severity`.
- Every request carries a `trace_id`; use it to follow a request across services.
- Log retention is **30 days**; audit logs are retained **1 year**.
