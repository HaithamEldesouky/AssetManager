# 029 - A Storekeeper's proposal can arrive as a file

**Type:** feature (small) · **Depends on:** 027, 028

## What changes

A delivery is twenty machines on a vendor's spreadsheet, not one asset typed twice. The
Storekeeper's Add Asset gains an **Import** path: pick an `.xlsx` or `.csv`, map its
columns, see the validation table, and submit the valid rows as **proposals** - one per
row, into 028's table, decided by the Admin as a batch or one at a time.

It reuses 027's `_map_import_columns` and `_validate_import_rows` rather than carrying its
own: the mapping guess and the validation rules are one fact, and two copies would drift
into a file the Admin's importer accepts and the Storekeeper's refuses. The Storekeeper is
a client and does not import `server.py`, so the mapping runs **on the server** - the client
posts the parsed rows to `POST /assets/propose` in a batch and shows what comes back. That
is also what keeps rule 10's line intact.

The batch is capped, like `POST /clients/log`'s is and for the same reason: the endpoint is
unauthenticated. An over-long file is refused with the count rather than half-accepted.

The Server GUI's proposals window groups a batch by the moment it arrived, so approving a
delivery is one decision rather than twenty.

## Verification

`tools/client-checks.py` for the window; `tools/server-checks.py` for the batch cap and for
a file whose rows collide with each other being refused as a file rather than row by row.

## Not in this ticket

Any new mapping or validation rule. If one is needed, it belongs in 027's helpers, where
both importers read it.

## As built

Done as filed, with two things the ticket left open decided here and one place
where following it exactly would have written a rule down twice.

- **The rules run on the server; the *reading* of the file does not.** The
  ticket asks for the mapping to run on the server and for the client to post
  the parsed rows, which means the client needs a reader - and
  `_import_file_rows` is in `server.py`, which no client imports (rule 10). So
  `POST /assets/import/preview` answers with the guess, the mapping check and
  the row verdicts, and `_read_import_file` in `storekeeper_app.py` is the one
  thing copied: openpyxl and the stdlib `csv`, which is a mechanism rather than
  a rule. Posting the workbook itself was the alternative and was rejected -
  handing somebody else's file to an unauthenticated endpoint to be parsed is a
  worse thing to offer the network than a list of strings.
- **The new rule went into 027's helpers, which is where the ticket says such a
  rule belongs.** Two of them: `_check_import_mapping`, which is the three
  refusals 027's window worded inline, now worded once and called by both
  importers; and `pending` on `_validate_import_rows`, so a row colliding with a
  proposal already waiting is refused in `_propose_asset`'s own sentence. It is
  optional rather than defaulted, because the Admin's importer writes the
  register directly and a proposal is not in its way.
- **A batch is a stamp, not a column.** Every row of one file carries the one
  `proposed_at` it was written with, and the Server GUI groups on that. A
  `batch_id` column would be a second copy of a fact those rows already hold -
  `client_commands` next door is the standing argument - and it would need a
  migration for a grouping.
- **All or nothing, which is more than the ticket asked for.** The ticket asks
  that a file colliding with itself be refused as a file. The same argument
  refuses a file for *any* bad row: the rows that went in are indistinguishable
  from rows somebody typed, and nothing says which half arrived. So the window
  offers the send only while there are no refusals, and the endpoint re-checks
  and refuses whole regardless.
- **`_propose_asset` gained `conn`, `proposed_at` and `log`**, which is
  `_save_asset`'s own shape. `log=False` is the one that is not cosmetic: a
  `_log_event` opens a connection of its own, and against the uncommitted batch
  transaction that is exactly the contention `_log_event` refuses to wait for -
  so the batch logs one entry after it commits.

## Verified

- `tools/server-checks.py` (125 groups), `tools/cascade-audit.py` (no drift) and
  `tools/client-checks.py` (12 groups) all exit 0.
- The Storekeeper's window driven end to end against a real server: the guess
  arrives and is shown as guessed on all four fields, the verdict table names a
  row with no identifier and a row the register holds, the send is refused while
  either is there, a clean file is proposed as one batch under one
  `proposed_at` with this installation's `client_id` on every row, and with the
  server unreachable the window opens, says nothing was proposed or queued, and
  leaves `pending_buffer.json` untouched.
- The real Asset Proposals window: three rows from one file shown under one
  parent reading "3 assets in one file", a proposal typed on its own still a row
  of its own, and one Approve on the parent writing all three through
  `_save_asset` and leaving the single proposal alone.

## Not done here

Mailing the Admin that a delivery is waiting stays 031's, as filed.
