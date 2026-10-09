# 011 - A system log across the Server, Storekeeper and Notifier

**Type:** feature · **Depends on:** nothing (but see "Sequencing")

## What is asked

Log every action of all three components.

## Where it stands today

**There is no logging anywhere.** `server.py` imports no `logging` and never calls
`app.logger`; the clients write nothing but `dev.out.log` / `dev.err.log`, which are
`dev-run.ps1`'s redirected stdout, and `launch.err.log`, which `applaunch.py` writes when
source mode fails to start. The only record of anything happening is the `transactions`
table itself and `client_commands`.

## The decisions to settle before writing code

**"Every action" is not a scope.** Three questions decide the size:

1. **Where does it live?** A table in `assets.db` (queryable, backed up, grows the file,
   and every write contends with the transaction writes) or a rolling file beside the
   server (cheap, but a second thing to collect). A table is the better fit for the
   Server GUI showing it; a file is the better fit for volume.
2. **Do the clients log locally, or ship to the server?** Shipping needs an endpoint, and
   that endpoint is **unauthenticated** like every other client channel (ADR-0002, ADR-0005)
   - so anything on the network can write to the log. Say plainly what that is worth
   before building it. Local files answer "what did this laptop do" without that exposure,
   and the check-in channel already exists if a summary should travel.
3. **What is an action?** Recommended floor: every write (transaction created, confirmed,
   rejected, cancelled, modified, deleted), every password check that fails, every admin
   console action, every client command issued and collected, and each app's start/stop.
   **Never the passwords themselves**, and nothing that is already a row somewhere.

## DECIDED (David Foster, on the ticket)

**Clients do both: they ship their logs to the server AND keep a local log.** Questions 2
is answered; 1 and 3 still need an answer from whoever implements this, within that.

What that decision costs, stated once so it is designed for rather than discovered: the
receiving endpoint is **unauthenticated**, like every other client channel (ADR-0002,
ADR-0005), so anything on the internal network can write to the server's log. That is
accepted. It is not a reason to skip the ordinary defences, which are the same ones
`POST /clients/checkin` already applies to values a caller on the network chooses:

- cap every field's length, and cap how much one request may carry;
- record the **source address** the server saw, beside whatever the client claims about
  itself, so a forged component name is visible as a mismatch rather than believed;
- never let a log write fail a real operation - a full or locked log must not stop a
  Transaction being recorded, confirmed or rejected;
- the local log is the client's own record and is **not** trusted to be the same as what
  arrived - the server's copy is what the Server GUI shows.

The local file is a rolling one with a size bound, for the reason `applaunch.py` already
writes `launch.err.log`: an engineer's laptop that cannot reach the server still has to be
able to say what it did.

## Scope

- Migration `007_system_log` creating the table, `init_db()` creating it idempotently as
  well, and a `down()` that **keeps it** - the same rule `004` and `005` follow.
- One writer function on the server, the way `_create_transaction` is the one writer of a
  Transaction, so the endpoint and the server's own logging cannot disagree about shape.
- The endpoint the clients ship to. Additive to the API table, and refused politely rather
  than fatally - a client whose log cannot be delivered keeps its local copy and carries on.
- A local rolling log in each client, written whether or not the ship succeeded.
- A retention answer for both ends. A log with no bound grows until the database is the
  problem; say what trims it and when, or say deliberately that nothing does and why.
- A Server GUI window to read it, filterable by component and by date.

## Sequencing

Not blocked by any ticket, but it edits `server.py` heavily and adds a schema block, a
migration and an API row - all places 009 also touches. **Run it after 009 lands** rather
than beside it.

## Cascade

- The schema block in `CLAUDE.md` (a new table), the migration rules section, the API
  table if an endpoint is added, the Server GUI section for the new window.
- `CONTEXT.md` glossary: "System Log" is a new domain term.
- Run all three gates.
