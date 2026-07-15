# Access Management & Secrets Runbook

Owner: Security & Platform Teams
Last reviewed: 2026-06-12

## Requesting production access

Production access is **just-in-time** and time-boxed; there is no standing admin access.

1. Request elevation: `opsctl access request --role prod-operator --duration 4h --reason "<ticket>"`.
2. A second team member must **approve** the request (four-eyes principle).
3. Access auto-expires after the requested duration (max **8 hours**).
4. All elevated sessions are recorded and audited.

## Roles

| Role | Grants | Approval |
|------|--------|----------|
| read-only | view dashboards, logs, configs | none |
| prod-operator | run runbooks, restart services, scale | one approver |
| prod-admin | modify infra, IAM, secrets | two approvers + security |
| break-glass | emergency full access | auto-approved, alerts security |

**break-glass** is for SEV1 emergencies only. Using it pages the Security team and
requires a written justification within 24 hours.

## Secrets management

- All secrets live in the central **secrets manager** — never in code, env files
  committed to git, or chat.
- Applications read secrets at startup via their IAM role; humans never see raw
  production secret values.
- Reference secrets by name/ARN, not value.

## Rotating a credential

1. Generate the new secret version: `opsctl secret rotate --name <secret>`.
2. The secrets manager stores it as `AWSCURRENT`; the previous stays as `AWSPREVIOUS`.
3. Restart or redeploy consumers so they pick up the new version.
4. Verify healthy, then the old version can be revoked.
5. **Rotation cadence:** database credentials every **90 days**, API keys every
   **180 days**, TLS certs auto-renew at **30 days** before expiry.

## Suspected credential leak

1. Treat as a **SEV2** (or SEV1 if production data is reachable) and page Security.
2. **Revoke first, investigate second** — rotate/disable the exposed credential immediately.
3. Review audit logs for use of the credential during the exposure window.
4. Rotate any credentials that share the same blast radius.
