# 025 - Asset uniqueness is enforced at the store, not at one window

**Type:** bug fix / hardening · **Depends on:** 024

## Finding

The duplicate refusal exists, and it is in the wrong place. `server.py:5180-5195`, inside
the Lookup Sheet window's `do_save`, walks the rows and refuses an identifier that is
already there, case-insensitively, naming the row that holds it. It is a good refusal.

**Nothing else runs it.** `POST /lookup/upload` replaces the whole sheet with whatever
base64 arrived and validates none of it, so a workbook with the same Asset Number twice is
accepted, and `_load_lookup_table` silently keeps only the last of them - the earlier row
is shadowed, not reported. 027's importer and 032's sync would each arrive at the same
gap and each be tempted to write their own copy of the check, which is what rule 10 exists
to prevent.

## What changes

The rule moves down to `_save_asset` (024's one writer) and to the schema:

- a unique index on `lower(asset_number)` where it is non-empty, and another on
  `lower(serial_number)`, in migration `009_asset_identity`, with `down()` dropping the
  indexes only - a pure performance-and-constraint artefact with no data in it, which is
  exactly what a `down()` is for;
- `_save_asset` refuses a collision and **names the row that holds the identifier**, the
  way the window already does, so every caller can report it rather than say "failed";
- the Lookup Sheet window keeps showing that message and stops computing it;
- `POST /lookup/upload` refuses a workbook whose rows collide with each other or with what
  it keeps, and says which row and which identifier. An upload is all-or-nothing: half an
  asset register is worse than the one that was there.

**A migration that finds existing duplicates cannot create the index.** It reports them and
refuses, naming each pair, rather than deleting one side - which of two rows describing one
asset is the real one is not a decision a migration gets to make.

## Case is not significant for an identifier either

Uniqueness above is case-insensitive, and so is **retrieval** - the two are one rule and
this ticket owns both. `_load_lookup_table` already keys the sheet on both identifiers
lowercased, so `GET /lookup`, rule 6 and both clients' auto-fill are case-insensitive
today; 024 moves that store into SQLite and this is what stops it being lost on the way.
The columns are declared `COLLATE NOCASE` and the unique indexes rest on that rather than on
each caller remembering to lower a string.

The stored spelling is the one that was typed, the way it is for an Engineer's name (034) -
what stops being significant is only whether two spellings differ by case. `NOCASE` folds
ASCII only; an identifier outside A-Z compares as bytes, which is the same limit 034 writes
down.

## Verification

`tools/server-checks.py` gains a group: that two rows differing only in case are one
collision, that an empty identifier never collides with another empty one (an asset may
have only a serial), that the upload endpoint refuses and writes nothing, and that the
message names the offending row.

## Not in this ticket

Any change to what a Transaction is checked against - rule 6 already reads the table
through `_load_lookup_table` and keeps doing so.

## As built

Done as filed, with the migration numbered `010_asset_identity` (034 took 008
and 024 took 009, which is what "the next free number at merge time" meant), and
one decision the ticket could not have made, because it only becomes visible
against the real data.

**The shipped Lookup Sheet contradicts itself, and a blanket refusal would have
been unshippable.** 6 of its 3462 rows share a Serial Number with another row -
`553JC5J`, `DPPMK3J`, `9MPMM3J`, `CN0TP223737317BJF02U`, `CN036WJX7426153O1G6L`,
`C02VQ4XRG8WN` - each pair carrying two distinct Asset Numbers. The first run of
this work was an `sqlite3.IntegrityError` inside `init_db()`, which is a server
that never starts, and the migration as filed would have refused on every
existing install for the same six rows.

So the rule the ticket asks for is kept and given one fallback, in
`_resolve_asset_identity` and in the migration's own `resolve`:

- **A value that names two assets names neither**, so it is cleared from every
  row holding it but the lowest id. Both assets are kept, each still carrying
  its other identifier - which is rule 5's shape, so each is still an asset -
  and one deterministic answer is left for whoever scans that barcode. The
  System Log records it as `assets.ambiguous_identifier`, naming each value,
  because an Admin looking for an asset by a serial that has stopped answering
  is the person who needs that line.
- **Where clearing would leave a row with no identifier at all**, nothing is
  cleared. That row would stop being an asset, and which of two rows describing
  one asset is the real one is still not a decision a migration gets to make.
  The migration refuses over exactly those, naming them; `init_db()` warns and
  starts, logging `assets.duplicate_identifier` - it runs on every boot, and a
  store that cannot record a movement today because of a duplicate created
  months ago is the worse failure.
- **The seed applies the same rule row by row** as it reads the sheet in, rather
  than inserting and letting the index decide, so a fresh install starts.

**`POST /lookup/upload` still refuses outright**, as the ticket asks, and that is
worth stating rather than smoothing over: an Admin uploading the department's
original workbook is told which asset of the sheet and which identifier, and has
to correct those six rows before that upload is taken. It is admin-initiated,
somebody is watching, and telling them is the audit that was asked for - where
the seed and the migration run with nobody watching and must not be what stops
the store. The round trip is self-consistent either way: what `GET /lookup/file`
exports is the deconflicted table, so downloading and uploading it back is not
refused.

**A `down()` does not put a cleared identifier back.** It was ambiguous before it
was cleared and restoring it into a build with no index to catch it reverses
nothing.

**`_save_asset` still refuses, and says so in its own words.** The Lookup Sheet
window stopped computing the message and stopped walking the rows it happened to
be showing; `write()` shows a `ValueError` bare rather than behind "the Lookup
Sheet was not written", which is the accurate sentence only for a write that
actually failed - a locked database, a disk.

## Verified

- `tools/server-checks.py` (120 groups), `tools/cascade-audit.py` (no drift) and
  `tools/client-checks.py` (12 groups) all exit 0.
- A real pre-010 install: the whole 3462-row sheet in a table with no collation
  and no indexes. `resolve` finds the six shared serials and nothing
  unresolvable; `up()` keeps all 3462 rows, leaves every one of them identified,
  puts both identifiers on `COLLATE NOCASE` and both partial unique indexes on;
  `GET /asset_types` answers the same seven types; `GET /lookup?q=dppmk3j`
  resolves mis-cased; `down()` keeps all 3462 and a second `up()` does not
  double them.
- A fresh `init_db()` over that same sheet seeds it, logs
  `assets.ambiguous_identifier`, and starts.
