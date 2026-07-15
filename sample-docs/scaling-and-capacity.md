# Scaling & Capacity Runbook

Owner: Platform Team
Last reviewed: 2026-05-30

## Autoscaling configuration

Services run on a container platform with horizontal autoscaling.

| Setting | Value |
|---------|-------|
| Min replicas | 3 |
| Max replicas | 30 |
| Target CPU utilization | 65% |
| Target memory utilization | 75% |
| Scale-up cooldown | 60 s |
| Scale-down cooldown | 300 s |

Autoscaling adds replicas when average CPU exceeds 65% for 60 seconds and removes
them when it stays below 45% for 5 minutes. Scale-down is intentionally slower to
avoid flapping.

## Handling a traffic spike

1. Confirm the spike is legitimate traffic (not a retry storm or abuse) in the
   traffic dashboard.
2. If autoscaling is keeping up (latency normal, no 5xx), do nothing — let it work.
3. If replicas hit **max (30)** and latency is climbing, **raise the ceiling**:
   ```
   opsctl scale set --service checkout-api --max-replicas 50
   ```
4. Check downstream limits — a scaled-up service can overwhelm the database
   connection pool (see Database Operations runbook) or a rate-limited dependency.
5. For a known event (sale, launch), **pre-scale** the day before:
   `opsctl scale set --service checkout-api --min-replicas 10`.

## Load shedding

When a dependency is saturated and scaling won't help, shed load rather than
collapse:
- Enable the priority queue: `opsctl feature enable load-shed --service checkout-api`.
- This returns HTTP 429 to low-priority/anonymous traffic while protecting
  authenticated checkout flows.
- Communicate to stakeholders; shedding is customer-visible.

## Capacity planning

- Review headroom monthly. Target steady-state peak below **60% of max replicas**.
- If sustained peak exceeds 60% of max for two consecutive weeks, raise min/max
  and revisit instance sizing.
- Keep at least **one full availability zone** of spare capacity for AZ failure.
