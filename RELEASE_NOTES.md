# SOMAS v1.1 — User Workspaces and Private Agent Ownership

October 20, 2026

## Shipped

- Local registration and login, email/password-based sessions, logout, profile editing, password changes.
- Per-user isolated Manager policy weights, organization graphs, specialist weights, histories, runs and feedback.
- Private **My Agents** directory and user account controls in the dashboard.
- Stronger SQLite schema using composite foreign keys for owner/org integrity.
- Account-scoped routes, hardened cookies and CSRF checks on account-authenticated writes.
- Tests for cross-user access denial, forged agent references, CSRF, session revocation and older SOMAS behavior.
- Preserves demo-mode training and optional frozen-LLM text drafting.

## Not yet included

- Business-level shared workspaces, user invitations, team roles or administrator management.
- Email verification, password-reset email delivery, 2FA, OAuth or SSO.
- Production-ready authorization auditing, durable distributed login rate limiting, cloud secrets/billing quotas, production HTTPS setup, data encryption at rest, GDPR controls or security certification.
- Real customer workflow integrations or autonomous business execution.

**v1.0 data will NOT be automatically claimed by the first registered account.** See README for the safe new DB convention.
