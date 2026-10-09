# 039 - The Register gets an interface

**Type:** refactor · **Depends on:** 036, 038 · **Found by:** architecture review, Sep 2026 · **Issue:** [#210](https://github.com/HaithamEldesouky/AssetManager/issues/210)

**Superseded by 041-043** — filed as three tickets instead of one, each a real seam
(Assets, Transactions, Engineers) with its own route and console adapter. This file is
kept for its Finding; the Scope below is not the one that shipped.

## Finding

The console and the routes read the same tables through different code.

`server.py` holds 137 `execute()` sites and 7 separate `sqlite3.connect()` calls - `get_db`
(3349), the two migration readers (3861, 3930), and four more inside the log and sync
readers (8206, 8385, 8455, 9460). The routes mostly inline their SQL. The console mostly
goes through small query functions - `_member_rows` (6021), `_load_assets` (4596),
`_load_proposals` (4996), `_client_rows` (7620), `_member_row` (5998), `_member_row_by_id`
(6005) - which are called from the windows and almost never from the routes.

So a column, a filter or a rule has to be found and changed in two places, and drifts
between them in the meantime. An engineer can appear in one view and not the other.

**The console reads the database directly on purpose.** `server.py:6027` records why: the
window must not depend on the listener being up. That constraint is correct and this ticket
keeps it - an interface is not a listener.

## Scope

One Register module owning every read and write of Assets, Transactions and Engineers. The
routes and the console windows become two adapters over it. Two adapters, so the seam is
real rather than hypothetical.

1. **The Register owns the connection.** `get_db` and the six query functions move behind
   it. The four stray `sqlite3.connect()` calls in the log and sync readers come with them.

2. **The console adapter calls it in-process.** No HTTP, no listener dependency. The
   guarantee at 6027 is preserved by construction.

3. **`tools/server-checks.py` calls the Register directly** for anything that is not
   testing HTTP. Today its helpers all take a database; after this they take a Register.

**This is the largest of the three and it goes last** - 036 and 038 prove the pattern on
smaller ground first. Do not start it before both have landed and merged.

## Not in this ticket

- The schema. No column moves, no migration.
- `_create_transaction`'s second writer. `_import_records_xlsx` (`server.py:4417`) inserts
  into `transactions` directly, and its own comment at 4412 admits it, which makes rule 6
  nearly true rather than true. That is a ticket of its own and is deliberately not folded
  in here - a refactor and a rule change in one commit is two tickets.
- Deleting the query functions. They move; whether they survive as the Register's own
  internals is an implementation choice.

## Cascade

- `CLAUDE.md` - "The files" table; rule 6 and rule 11 if either changes where a fact is
  read.
- `docs/reference/architecture.md`, `docs/reference/database.md` - the schema block stays,
  but the sentence about who reads it changes.
- `docs/reference/api.md` - only if an endpoint's shape moves. It should not.
- `tools/package.ps1:147` `$SourceFiles`.
- `tools/cascade-audit.py` - the database-column check reads `server.py`; point it at
  wherever `CREATE TABLE` ends up.
- ADR-0004 (the database can be moved) - confirm `db_path` still resolves through one
  place.

## Verification

- `ast.parse()` every file touched.
- `py -3.12 tools/gate.py --all`.
- Every endpoint that reads or writes, hit against a running server, before and after,
  with the responses diffed.
- Open every console window and confirm each shows what the matching endpoint returns -
  that agreement is the whole point of the ticket.
- Start the console with the listener stopped and confirm the windows still read.
