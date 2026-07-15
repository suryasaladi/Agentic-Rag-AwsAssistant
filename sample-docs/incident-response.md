# Incident Response Runbook

Owner: SRE Team
Last reviewed: 2026-05-20

## Severity levels

| Severity | Definition | Examples | Response time |
|----------|------------|----------|---------------|
| SEV1 | Full outage or data loss affecting most customers | Checkout down, auth broken globally | Immediate, 24/7 page |
| SEV2 | Major degradation, significant subset affected | 30% error rate in one region | Page within 15 min |
| SEV3 | Minor/partial degradation, workaround exists | Slow dashboards, one non-critical feature down | Next business hour |
| SEV4 | Cosmetic or low-impact | Typo, minor UI glitch | Backlog |

## Who to contact / escalation path

1. **Primary on-call** is paged automatically by the alert. Ack within 5 minutes.
2. If primary does not ack in 5 minutes, the page **auto-escalates to secondary
   on-call**.
3. For SEV1/SEV2, the on-call engineer must page the **Incident Commander (IC)**
   rotation and open a dedicated incident channel.
4. If the incident involves customer data exposure, page the **Security on-call**
   immediately — do not wait.

On-call schedules live in the paging tool; the current on-call can also be found
with `opsctl oncall who --team sre`.

## Declaring an incident

1. Open a channel named `#inc-<date>-<short-name>`.
2. Post the severity, affected service, customer impact, and start time.
3. Assign roles: **Incident Commander** (coordinates), **Comms** (status page +
   stakeholders), **Ops** (hands on keyboard).
4. Update the public **status page** for any SEV1/SEV2 within 30 minutes.

## During the incident

- One person (Ops) makes changes; IC approves. Avoid multiple people acting at once.
- Post updates in the channel at least every **15 minutes** for SEV1, **30 minutes** for SEV2.
- Prefer **mitigation over root-cause**: roll back, fail over, or shed load first;
  investigate afterward.

## After resolution

- Downgrade severity and mark the incident resolved when metrics are stable for 30 minutes.
- A **blameless postmortem** is required within **5 business days** for every SEV1 and SEV2.
- Track action items to closure; tag them `incident-followup`.
