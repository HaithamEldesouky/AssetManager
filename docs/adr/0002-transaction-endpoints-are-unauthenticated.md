---
status: accepted
---

# Transaction endpoints stay unauthenticated

`POST /transactions`, `POST /confirm/<id>` and `POST /reject/<id>` accept any
request that reaches the port. No password, no token, no client identity. Every
other mutating endpoint — `/members`, `/members/delete`, `/transactions/delete`,
`/lookup/upload`, `/admin/*` — requires the admin password.

This was found during a structural sweep and is recorded here because it is a
decision, not an oversight, and nothing in the code said so.

**Since #209 the code says so.** Each of the three carries
`door(DOOR_OPEN, why=...)` under its `@app.route`, naming this decision at the
route, and `tools/server-checks.py` refuses a route that declares nothing at
all. The decision is unchanged - what changes is that an absent line is no
longer how it is expressed, so a route left open by mistake no longer reads in
the source exactly like these three. Every other open route in `server.py` got
the same line and its own reason, this ADR being the one several of them name.

## What it means in practice

Anyone who can reach `asset-server:8081` can create a transaction against any
engineer's name, and can confirm or reject any pending transaction on their
behalf. The record will look exactly like a genuine one. There is no audit trail
that distinguishes them, because there is nothing to distinguish them by.

## Why it stays

The apps have no identity to authenticate with. The Notifier knows only which
engineer it was installed for — a value in its own `config.json`, editable by
whoever runs the laptop. Giving each engineer a credential the Notifier holds
would move the secret onto the same machine as the attacker we would be
defending against, and the engineer's own password (`/auth/verify`) exists for
unlocking their own settings, not for signing their confirmations.

The system's actual threat model is mistakes, not adversaries: an internal
Windows domain, four known engineers, one storekeeper, and a stock list whose
worst-case loss is a wrong row in a spreadsheet. The controls that matter here
are the ones that already exist — the lookup sheet rejecting unknown assets, the
duplicate-pending check, the 24h auto-accept, the admin password on anything
destructive.

Adding a shared secret to the three endpoints would also be a breaking wire
change across four independently updated apps, in exchange for a secret that
ships inside an exe on every laptop. That is worse than honest: it would read
like authentication without being any.

## When to revisit

- If the API is ever reachable from outside the internal network. Under IIS
  (ADR-0001) that is a binding away, so this ADR is the reason to check.
- If transaction history is ever used for anything with consequences —
  chargeback, payroll, an audit anyone answers for.
- If the exes get code-signed and a per-machine credential becomes storable in
  a way an engineer cannot trivially read.

Any of those turns this from a reasonable trade into a real hole.
