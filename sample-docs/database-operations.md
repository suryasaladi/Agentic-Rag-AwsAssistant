# Database Operations Runbook

Systems: Primary PostgreSQL cluster (`orders-db`), read replicas, automated backups
Owner: Data Platform Team
Last reviewed: 2026-06-10

## Backups

- **Automated snapshots** run every 6 hours and are retained for **35 days**.
- **Point-in-time recovery (PITR)** is enabled with transaction logs retained for
  **7 days**, allowing restore to any second within that window.
- Backups are stored encrypted (KMS) and replicated to a second region nightly.

Verify the last successful backup:
```
opsctl db backups list --cluster orders-db --limit 5
```

## Restoring from a backup

Restores always create a **new** cluster; you never restore in place over a live
database.

1. Identify the target time or snapshot:
   `opsctl db backups list --cluster orders-db`
2. Start the restore into a new cluster:
   ```
   opsctl db restore --cluster orders-db --to-time "2026-06-10T14:30:00Z" --new-cluster orders-db-restore
   ```
3. Wait for the new cluster to reach **available** (10–40 min depending on size).
4. **Validate** the restored data (row counts, latest known record) before any cutover.
5. To cut over: put the app in maintenance mode, repoint the connection string /
   DNS to the restored cluster, then take it out of maintenance.
6. Keep the old cluster for 48 hours before deleting, in case of rollback.

RTO target: **1 hour**. RPO target: **5 minutes** (via PITR).

## Failover to a replica

If the primary is unhealthy but data is intact:
1. Confirm replica lag is low: `opsctl db replica-lag --cluster orders-db`
   (safe if lag < **10 seconds**).
2. Promote the replica: `opsctl db failover --cluster orders-db --promote replica-1`.
3. The promoted replica becomes the new primary; the app reconnects automatically
   via the cluster endpoint.
4. Provision a new replica to restore redundancy.

## High connection count / pool exhaustion

If you see `too many connections`:
- Check active connections: `opsctl db connections --cluster orders-db`.
- The pgbouncer pool max is **200**; the DB `max_connections` is **500**.
- Kill idle-in-transaction sessions older than 5 minutes before scaling the pool.
- Do **not** raise `max_connections` without Data Platform review — it increases
  memory per connection and can OOM the instance.
