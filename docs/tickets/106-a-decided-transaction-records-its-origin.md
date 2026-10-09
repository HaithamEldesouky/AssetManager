# 106 - A decided Transaction records its Origin

**Type:** feature · **Depends on:** none · **Issue:** [#282](https://github.com/HaithamEldesouky/AssetManager/issues/282)

## Finding

A Transaction's row says that it was Confirmed or Rejected but not where the
answer came from. `transactions` has no such column (`server.py` `init_db`,
`docs/reference/database.md`), and the System Log's `transaction.confirmed` and
`transaction.rejected` entries record only `address=_client_addr()` - no actor,
no client. An Auto-Approved or Auto-Accepted Confirmed is a different kind of
answer from one an Engineer gave at the desktop, and nothing in the row records
which.

## Design

**Origin** (`CONTEXT.md`) is one of `desktop`, `auto`. It is decided by
the Asset Server from the route the answer came through, never read from the
request body.

- New nullable TEXT column `transactions.origin`.
- `POST /confirm/<id>` and `POST /reject/<id>` write `desktop`.
- `_create_transaction` writes `auto` when it Auto-Approves; `_auto_accept_pass`
  writes `auto` for every row it Auto-Accepts.
- Migration backfill: `auto` where `auto_approved = 1`, otherwise NULL. NULL means
  "decided before Origin existed" and shows no label. Do not guess `desktop` for
  old rows.
- `origin` is added to every response that already returns a Transaction row
  (`GET /pending/<member>`, `GET /transactions`, and any other reader returning
  the row). Additive only: older Notifiers ignore it.
- `transaction.confirmed`, `transaction.rejected` and `transaction.auto_accepted`
  System Log entries carry `origin` and the acting Engineer in their data.

## Scope

- Migration `017_transaction_origin.py` beside the existing migrations (016 is
  the latest), with `up` and `down`, in the existing migration style.
- `init_db()`'s idempotent `ALTER TABLE` for the column.
- The three writers above, in `server.py` and `register_transactions.py`.
- The readers that return Transaction rows.
- The System Log entries' data, and their sentences if the sentence names the
  actor.

## Not in this ticket

- Any label in any window (107).

## Coverage

New checks in the server suite (`docs/CODING_STANDARDS.md` names which file):
confirm and reject write `desktop`; an Auto-Approve Engineer's creation writes
`auto`; an Auto-Accept pass writes `auto`; the migration backfills `auto` only
where `auto_approved`; `origin` appears in `/pending` and `/transactions`
responses; a body field named `origin` is ignored.

## Cascade

- DB column row: the migration, `init_db()`'s `ALTER TABLE`, and the schema
  block in `docs/reference/database.md`.
- Endpoint shape: the `/pending`, `/transactions`, `/confirm`, `/reject` rows
  in `docs/reference/api.md`.
- `_log_event` calls: their rows in `docs/system-log-events.md` and their
  phrases in `EVENT_SENTENCES` in `server_log.py`.

## Verification

- `ast.parse()` every edited Python file.
- Against a running server: create, confirm, reject; read `/transactions` and
  see `origin`. Run the migration up and down on a copy of a real `assets.db`.
- `py -3.12 tools/gate.py` passes.

## Done when

Every newly decided Transaction carries an Origin the server chose, readers
return it, older Notifiers behave exactly as before.
