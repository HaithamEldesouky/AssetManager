# 024 - Assets move into the database; the sheet becomes an import/export format

**Type:** refactor (storage) · **Depends on:** 023 · **Needs an ADR**

## What changes

`asset_lookup.xlsx` stops being the store and becomes a format. The assets live in a new
SQLite table beside the Transactions that are recorded against them:

```
assets
  id             INTEGER PRIMARY KEY AUTOINCREMENT
  asset_number   TEXT DEFAULT ''
  serial_number  TEXT DEFAULT ''
  asset_type     TEXT NOT NULL
  asset_model    TEXT DEFAULT ''
  created_at     TEXT NOT NULL
  created_by     TEXT DEFAULT ''
  updated_at     TEXT DEFAULT ''
```

Migration `008_assets` creates it, `init_db()` creates it idempotently as well - the
both-ways pattern `004`, `005` and `007` already use - and **`down()` keeps the table**,
for the reason every other `down()` here keeps one: an older build never reads it, while
dropping it would destroy the only copy of the asset register the moment somebody
downgrades to look at it.

## Why, rather than keeping the sheet

The sheet is read on **every** `_load_lookup_table()` call - every Transaction submitted,
every keystroke in a lookup field - and written by replacing the whole workbook. Three
tickets in this batch need something the sheet cannot give:

- **025** needs a uniqueness rule the store enforces, not a check one window happens to run.
- **027** needs to write a validated subset of an import without rewriting rows nobody touched.
- **032** needs row-level updates from an external system, concurrently with live reads.

A whole-workbook rewrite on every sync, under a threaded Flask that re-reads the file on
every request, is the shape of the defect rather than a way to avoid one. And "audit the
asset in the db" is what was asked for; with the sheet it stays a figure of speech.

## Where the sheet still appears

- **First run seeds the table.** `DEFAULT_LOOKUP_B64` is unchanged and still extracted to
  disk; on a database with no `assets` rows, its contents are loaded in once. A migration
  on an existing install imports whatever `asset_lookup.xlsx` holds at that moment, so no
  deployment loses its register.
- **`GET /lookup/file`** still serves an xlsx - generated from the table now, not read off
  disk. It is an export.
- **`POST /lookup/upload`** still takes a base64 xlsx and still demands the admin password
  (rule 11). It replaces the table's contents rather than the file. Its shape on the wire
  does not change, so no client moves.
- `_save_lookup_raw` and `_load_lookup_raw` are replaced by `_save_asset` / `_delete_asset`
  / `_load_assets`, and `_save_asset` becomes the **one writer**, the way
  `_create_transaction` and `_log_event` are. The Lookup Sheet window and the upload
  endpoint both go through it.

## What must not change

`_load_lookup_table()` keeps its signature and its return shape - a dict keyed on both
lowercased identifiers - because rule 6, `GET /asset_types`, `GET /lookup` and the Server
GUI's Add Transaction all read it. Only its body moves from openpyxl to SQL. No endpoint
changes shape; no client is touched.

## Cascade

`CLAUDE.md` rules 2, 6 and 11, the schema block, the API table's four lookup rows and the
Server GUI's Lookup Sheet bullet; `CONTEXT.md`'s glossary; `tools/cascade-audit.py`'s
schema check gains the new table; `tools/server-checks.py` gains a group - that the
migration and `init_db()` produce the same columns, that `down()` keeps the table, that a
first run seeds from the embedded sheet, and that rule 6 still refuses an asset the table
does not hold.

An **ADR** records why the sheet stopped being the store and why it is still the interchange
format - the same question ADR-0004 answers for the database's location.

## Verification

`tools/migrate.ps1 -DryRun` against a copy of a real `assets.db`; then a real migration and
`GET /asset_types` answering what the sheet answered before it. All three gates exit 0.

## Not in this ticket

Uniqueness (025), the Model dropdown (026), import mapping (027). This ticket moves the
store and changes no rule about what may go in it.

## As built

Done as filed, with the numbering and four decisions worth recording.

**The migration is `009_assets`, not `008`.** 034 landed first and took `008`,
which is what the ticket meant by "the next free number at merge time". The
tickets behind this one shift by the same amount.

**The word did not move with the storage.** CONTEXT.md's glossary calls this
list the **Lookup Sheet** and says to avoid "asset register"; the Storekeeper
says "lookup sheet" in six places, the refusal code is `not_in_lookup`, and the
Server GUI window is called Lookup Sheet. So the table is where the Lookup Sheet
is kept, the glossary entry says so, and no message anywhere was reworded - a
rename of the domain term would be its own ticket across all three clients, and
half-done it would leave the system saying two things.

**`_xlsx_asset_rows` reads a path or a stream.** The seed hands it the sheet
beside the server; `POST /lookup/upload` hands it the uploaded bytes, so an
upload is parsed before anything is written and no file is staged on disk to be
cleaned up - one reader, and the only reader, of the interchange format.

**The upload endpoint no longer writes `asset_lookup.xlsx`.** It replaces the
table in one transaction. The file beside the server is left as the seed this
install read in and goes stale on purpose; `GET /lookup/file` generates a
workbook from the table instead of serving it. ADR-0011 has the reasoning.

**Seeding is guarded on the table being empty, not on the file being absent.**
An Admin who removes an asset must not find it back after a restart, and
`tools/server-checks.py` asserts exactly that.

## Verified

- `tools/server-checks.py`, `tools/cascade-audit.py`, `tools/client-checks.py`
  all exit 0 (117 / no drift / 12 groups).
- A database at schema v8 holding the real 3462-asset sheet: dry run changes
  nothing, the migration carries all 3462 in, `GET /asset_types` answers the
  seven types the sheet answered, `down()` keeps every row and a second `up()`
  does not double them.
- `GET /lookup/file` round-trips through `POST /lookup/upload` with every asset
  unchanged; rule 6 still refuses an asset the table does not hold; the Server
  GUI's Add Transaction still resolves and corrects from it.
