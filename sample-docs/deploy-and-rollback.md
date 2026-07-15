# Deployment & Rollback Runbook

Service: **checkout-api** (also applies to all services on the standard pipeline)
Owner: Platform Team
Last reviewed: 2026-06-01

## Deployment overview

Deployments run through the CI/CD pipeline (`build → test → canary → full rollout`).
A normal production deploy is triggered by merging to `main`, which the pipeline
promotes automatically through the stages below.

| Stage   | Traffic | Bake time | Auto-promote |
|---------|---------|-----------|--------------|
| canary  | 5%      | 10 min    | yes, if healthy |
| phased  | 50%     | 15 min    | yes, if healthy |
| full    | 100%    | —         | —            |

A deploy is considered **healthy** when, during the bake window:
- HTTP 5xx error rate stays below **1%**
- p99 latency stays below **800 ms**
- no new SEV1/SEV2 incident is opened for the service

## Rollback procedure for a failed deploy

Roll back when error rate or latency breaches the thresholds above, or when a
deploy introduces incorrect behavior confirmed by on-call.

1. **Stop the rollout.** In the pipeline UI, click **Halt** on the active
   deployment. This freezes traffic shifting but does not revert.
2. **Trigger the rollback.** Run:
   ```
   opsctl deploy rollback --service checkout-api --to last-stable
   ```
   `last-stable` is the most recent version that completed a full 100% rollout.
3. **Verify traffic shift.** Within ~2 minutes, 100% of traffic should route to
   the previous version. Confirm in the traffic dashboard that the new-version
   weight drops to 0%.
4. **Confirm recovery.** Watch the error-rate and latency panels for 5 minutes.
   They should return to baseline. If they do not, escalate to a SEV2 incident.
5. **Freeze deploys.** Run `opsctl deploy freeze --service checkout-api` to block
   further deploys until the root cause is understood.
6. **Record it.** Add a note to the incident channel and open a rollback ticket
   tagged `postmortem-needed`.

Rollback typically completes in **under 5 minutes**. If it exceeds 15 minutes,
page the Platform on-call lead.

## Rolling back a database migration

Code rollback does **not** revert schema changes. If the failed deploy included
a migration:
- Forward-only migrations (add column, add table) are safe to leave in place.
- Destructive migrations (drop/rename column) must be reverted with the paired
  `down` migration: `opsctl db migrate down --service checkout-api --steps 1`.
- Never run a `down` migration during peak traffic without DBA sign-off.
