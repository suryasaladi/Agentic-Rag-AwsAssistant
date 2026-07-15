# Sample Knowledge Base Docs

Synthetic Cloud Ops runbooks for a fictional platform, used to seed and test the
Bedrock Knowledge Base behind the Cloud Ops Assistant. Upload these to your S3
bucket (Part 1), then Sync the knowledge base.

| File | Covers |
|------|--------|
| `deploy-and-rollback.md` | Deploy stages, health thresholds, rollback steps, migration rollback |
| `incident-response.md` | Severity levels, escalation path, declaring/running incidents, postmortems |
| `database-operations.md` | Backups, point-in-time restore, replica failover, connection limits |
| `scaling-and-capacity.md` | Autoscaling settings, traffic spikes, load shedding, capacity planning |
| `monitoring-and-alerts.md` | Golden signals, alert thresholds, alert response, logs/tracing |
| `access-and-secrets.md` | JIT access, roles, secrets management, credential rotation & leaks |

## Test questions (should be answerable from the docs)

- What's the rollback procedure for a failed deploy?
- What error rate is considered unhealthy during a deploy?
- Who do I contact for a SEV1 incident and how fast must it be acked?
- How do I restore the orders database to a specific point in time?
- What are the autoscaling min and max replicas?
- When should I use break-glass access?
- How often are database credentials rotated?

## A question deliberately *not* covered (tests honesty)

- "What's our Kubernetes ingress controller?" — not in these docs. A well-behaved
  RAG setup should say it doesn't know rather than inventing an answer.

> All content here is fictional and safe to make public. Replace with your real
> runbooks when you move past the POC.
