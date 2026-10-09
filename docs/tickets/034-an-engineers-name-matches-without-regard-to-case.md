# 034 - An Engineer's name matches without regard to case

**Type:** bug fix / hardening · **Depends on:** 023 · **Lands before 024**

## Finding

`team_members.name` is `TEXT PRIMARY KEY` with no `COLLATE` clause, and there is no
`COLLATE` anywhere in `server.py` or in any migration. SQLite's default is `BINARY`, so
every `WHERE name=?` in this file - and there are eleven of them - matches bytes. So does
every `WHERE team_member=?` over the Transactions.

An Engineer's name is a **person**, and a person typed in a different case is the same
person. Today they are not, and the failures are not cosmetic:

- **`_save_member` creates a second Engineer.** It reads `SELECT * FROM team_members WHERE
  name=?` (`server.py:3375`) to decide between an update and an insert, so `alice
  carter` typed with different capitalisation misses the row and inserts
  beside it. The list then holds two people who are one person, each with their own Own
  Password, their own profile and their own Auto-Approve flag.
- **`/auth/verify` answers `no_member`** for a name that differs only in case, so the
  Engineer cannot open Settings and cannot replace a Temporary Own Password - and the
  message tells them the Engineer does not exist.
- **`GET /pending/<member>` returns nothing**, which is the sharp one: a Notifier whose
  `current_user` is cased differently from the row polls for ever, is offered nothing, and
  reports no error. An Engineer who stops being asked to confirm anything is the one
  failure that app exists to prevent (`CLAUDE.md`, Notifier).
- **`_create_transaction`'s auto-approve read** (`server.py:3056`) misses the row and the
  Transaction is recorded as Pending against an Engineer who has no Notifier, where it sits
  until the 24h Auto-Accept resolves it with nobody watching.

## What changes

**Matching is case-insensitive; the spelling is kept as it was typed.** The stored name is
what an Admin entered and what is shown; what stops being significant is only whether two
spellings differ by case.

- A migration (**the next free number at merge time**) rebuilds `team_members` with
  `name TEXT PRIMARY KEY COLLATE NOCASE`. SQLite cannot alter a column's collation, so this
  is a create-copy-drop-rename inside the one transaction, carrying every column and every
  value across. `init_db()` gets the same DDL, idempotently, the both-ways pattern the other
  tables use. `down()` rebuilds it back to `BINARY` **and keeps every row and column** - the
  rule that a `down()` never drops data holds here as everywhere.
- **A database that already holds a case-collision cannot take the index, and the migration
  refuses**, naming each pair rather than choosing between them. Which of two rows is the
  real Engineer - and whose Own Password, permissions and Transactions survive - is not a
  decision a migration gets to make. The same answer 025 gives for a duplicated asset.
- `transactions.team_member` is a **label, not a key** - it is the name as it was at the
  time, deliberately unchanged when an Engineer is renamed or removed - so it gets no
  constraint. What it gets is that every query filtering on it compares case-insensitively
  (`team_member = ? COLLATE NOCASE`), so a row written before this lands still belongs to
  its Engineer. `GET /transactions?member=`, `GET /pending/<member>`, `/stats` and the
  export all go through that.
- The two places a **client** scopes by identity rather than displays - the Notifier's
  `_queue_rows` (`notifier_app.py:767`, the scope 016 fixed) and its pending count - compare
  casefolded. The Storekeeper's history filters and its per-member counts are display
  filters over names the server handed back, so they stay as they are.
- `_save_member` reads the existing row through the same collation, so a re-cased name is an
  **update of that Engineer's spelling**, never a second Engineer.

## Passwords do not change, and this ticket says so

**Every password stays case-sensitive** - the admin password, each capability password, and
each Engineer's Own Password. A name is an identifier and a password is a secret; folding
case on a secret throws away entropy and would silently weaken every value already stored
under ADR-0008. Nothing in `_hash_password`, `_admin_password_ok`, `verify_password` or
`verify_admin_password` is touched by this ticket.

## What NOCASE does not do

SQLite's `NOCASE` folds **ASCII only**. Names outside A-Z are compared as bytes, exactly as
today. Every name this department uses is Latin, so this is a limit worth writing down
rather than a defect to engineer around - and a fold that pretended otherwise would be a
Python-side normalisation the database could not enforce.

## Cascade

`CLAUDE.md`'s schema block (the `team_members` row gains the collation, and the note about
why the name is the key), `CONTEXT.md`'s glossary where it defines an Engineer,
`tools/cascade-audit.py`'s column check.

## Verification

`tools/server-checks.py` gains a group: `_save_member` with a re-cased name updates rather
than inserts and the stored spelling becomes the new one; `/auth/verify`, `/pending`,
`/transactions?member=` and the auto-approve read each answer for a name cased differently;
a Transaction written before the change still belongs to its Engineer; the migration refuses
a database holding a collision, naming both; `down()` keeps every row; and - stated as its
own assertion so it cannot be lost in a later sweep - a password differing only in case is
still **refused**.

`tools/client-checks.py`: the Notifier's queue scope holds for a `current_user` cased
differently from the row.

## Why it lands before 024

It rewrites the `team_members` block of `CLAUDE.md`'s schema section, which 024 also
rewrites when it adds `assets`. Git merges by line. It is independent of the asset chain
otherwise, so it goes in second - after 023, before 024 - and the chain rebases once.

## Not in this ticket

Asset identifiers. Those are already matched case-insensitively - `_load_lookup_table` keys
the sheet on both identifiers lowercased - and **025** is what carries that into the store
as an enforced rule rather than a convention.

## As built

Done as filed. Three things worth recording.

**`init_db()` warns where the migration refuses.** Both rebuild the table, and both meet
the same case a rebuild cannot decide: two rows already differing only in case, which the
new primary key cannot hold. The migration is a deliberate act with somebody watching, so
it raises naming every pair and writes nothing. `init_db()` runs on every boot, so it
leaves the table in the shape it found it, logs `members.name_collision` at `warn` naming
both spellings, and starts - a server that refuses to start because of a duplicate
somebody created months ago is a store that cannot record a movement today.

**`_create_transaction` writes the Engineer's own spelling.** The two queries against
`transactions.team_member` say `COLLATE NOCASE`, which covers the server's own reads, but
each client filters its fetched rows with a plain `==` against its `current_user`. Rather
than chase those, the row is stamped with the name as the Engineer is stored, whenever the
name names an Engineer at all; a name no Engineer holds is written exactly as it was sent,
since there is nothing to canonicalise it to.

**The `CREATE TABLE` carries the collation as well as the rebuild.** A fresh database would
otherwise be created binary and immediately rebuilt, which works and is a rebuild nobody
needs; with it declared, `_ensure_member_name_nocase` returns early on a database it just
made and the only rebuild is the one an older database actually needs.

`tools/client-checks.py` got the case leg inside the group that already opens the
Dashboard, not a group of its own - the stubbed `NT.api` there also had to fold case in
its own `member` filter, since it stands in for `GET /transactions`, which does.
