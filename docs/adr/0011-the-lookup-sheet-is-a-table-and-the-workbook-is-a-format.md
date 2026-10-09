---
status: accepted
---

# The Lookup Sheet is a table, and the workbook is a format

The assets the department owns live in the `assets` table in `assets.db`, beside
the Transactions recorded against them. `asset_lookup.xlsx` is how that list is
exported, edited elsewhere and put back - an interchange format, and the copy a
brand-new install starts from - rather than the store it was until 024.

Nothing about the list itself changed. It is still the Lookup Sheet, still the
sole authority on which assets and which Asset Types exist (rules 2 and 6),
still admin-password-only to change (rule 11), and `_load_lookup_table()` still
hands back the same dict keyed on both lowercased identifiers. What moved is
where the rows are kept.

## Why the workbook stopped being the store

It was read on **every** call: every Transaction submitted, every keystroke in
either identifier field of two different forms, every `GET /asset_types`, every
repaint of the Lookup Sheet window. 3462 assets, parsed out of a zip archive,
per request, on a threaded Flask.

It was written by **rewriting the whole file**. Correcting one asset's model
rewrote all 3462 rows, and a failure part way through left a truncated workbook
with nothing to go back to - the previous contents having been the only copy.

Three things asked for in this batch cannot be built on that shape:

- **Uniqueness enforced by the store** (025). A unique index is a property of a
  table. In a workbook it is a loop somebody remembers to run, in each window
  that writes - which is exactly the bug: the Lookup Sheet window checked for a
  duplicate identifier and `POST /lookup/upload` did not.
- **An import that writes a validated subset** (027). Mapping and validating an
  uploaded file means writing the rows that passed and leaving the rest to be
  corrected. Whole-file rewriting can only write all of it.
- **Row-level updates from an external system** (032), arriving while the store
  is being read. Two writers and a live reader on one workbook is not something
  that can be made safe; in SQLite it is what the file already does.

And "audit the asset in the db", which is what was asked for, stays a figure of
speech while the assets are not in the db.

## Why the workbook stays

It is what the department already has, what somebody edits when fifty assets
arrive at once, and what the exe ships embedded so a fresh install is not born
empty. So `GET /lookup/file` generates one from the table and `POST
/lookup/upload` replaces every asset from one, both with exactly the shape they
had before - four columns in the same order, the same base64 body, the same
`{status, assets_loaded}` answer. A Storekeeper built before this change
uploads and downloads as it always did, which is what makes this a storage
change rather than a wire change.

The file beside the server is deliberately **not** kept in step. It is the seed
this install read in, it goes stale the moment an asset is corrected, and
`GET /lookup/file` never serves it - because the question that endpoint answers
is what this server holds *now*, and a file written months ago cannot answer it.
Keeping it current would mean a whole-workbook rewrite on every change, which is
the thing being removed.

## One writer

`_save_asset` is the only thing that writes an asset row and `_delete_asset` the
only thing that removes one, the way `_create_transaction` is the only writer of
a Transaction and `_log_event` of a System Log entry. The Lookup Sheet window
and the upload endpoint both go through them.

That is where an asset is held to having an Asset Type and at least one
identifier - the same shape rule 5 holds a Transaction to. It was two separate
checks in two windows before, and the upload door had neither.

Uniqueness followed in 025, in that same function and in two partial unique
indexes under it: an identifier names one asset, matched without regard to case,
and an empty identifier is not an identifier. It was deliberately not part of
this ticket - a storage move that could also refuse to start is two failures
wearing one commit - and it turned out to need the room: the shipped sheet
itself holds 6 serials naming two assets each, so 025 clears a shared identifier
rather than refusing over it wherever both assets keep another identifier, and
refuses only where a row would be left with none.

## Both ways in, and seeding exactly once

Migration `009_assets` creates the table and fills it from the
`asset_lookup.xlsx` beside the **database**; `init_db()` creates it idempotently
and fills it when it is empty, from the one beside the **server**. Two paths
because they answer different situations: a fresh install has no sheet but the
embedded one, and an install whose `db_path` moved the database to another
volume (ADR-0004) has no sheet beside that file for the migration to find. An
unreadable sheet leaves the table empty in both, rather than refusing to start:
an empty Lookup Sheet refuses every Transaction, which is visible within a
minute and is fixed by uploading a sheet, while a server that will not start is
neither.

Seeding is once, guarded on the table being empty and not on the file being
present. An Admin who removes an asset must not find it back after a restart.

## A downgrade keeps the table

The same answer `004`, `005` and `007` give, with one more turn in it. An older
build reads the workbook and never queries `assets`, so keeping the table costs
it nothing. Dropping it would throw away every asset added, corrected or
imported since the upgrade - and the workbook on disk is a copy from before the
move, so there would be nothing left to reconstruct them from.

## What was rejected

**Keeping the workbook and adding a cache.** A read-through cache answers the
read cost and none of the write cost, and it adds the invalidation question to
every writer - including the ones 027 and 032 add. The defect is the whole-file
rewrite, and a cache does not touch it.

**A `lookup.db` of its own, beside the main database.** Two files to back up,
two to move when `db_path` changes, two for `update.ps1` to put in
`rollback/`, and a foreign key that could never be declared. The assets and the
Transactions recorded against them are one register.

**Referencing the asset row from `transactions`.** A Transaction records the
identifiers as they were at the time and must stay readable after the asset is
removed; an `asset_id` would either forbid the removal or leave dangling rows
claiming an asset that is no longer described anywhere. Rule 6 is a check at
creation time, not a relationship, and that is what keeps a five-year-old
Transaction legible.
