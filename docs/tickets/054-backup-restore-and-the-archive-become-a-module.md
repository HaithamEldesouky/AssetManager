# 054 - Backup, restore and the archive become a module

**Type:** refactor · **Depends on:** 053, and 042 (see the Finding) · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#228](https://github.com/HaithamEldesouky/AssetManager/issues/228)

## Finding

The fifth of 046's six, re-derived against the 9,826-line tree 043 left.

Three banners, one contiguous run:

- `# ─── Schema migrations ───` - `server.py:3795`.
- `# ─── Backup and Restore (A13, ADR-0019) ───` - `server.py:3982`.
- `# ─── Archive (export / import records) ───` - `server.py:4293`.
- The run ends at `4407`, immediately before `# ─── Lookup helpers ───` at `4408`.

4407 - 3795 + 1 = **613 lines**. 046 said `3801-4255`, 455 lines.

Inside it: `_migration_files` (`3808`), `_schema_version` (`3837`), `_backup_db` (`3845`),
`run_migrations` (`3858`), `_migrate_cli` (`3943`), `_sha256_file` (`4028`),
`_latest_schema_version` (`4041`), `_backup_members` (`4062`), `_take_backup` (`4086`),
`_read_backup_manifest` (`4142`), `_verify_backup` (`4172`), `_restore_target` (`4205`),
`_restore_preflight` (`4221`), `_restore_backup` (`4245`), `_export_records_xlsx`
(`4300`), `_log_cell` (`4322`), `_export_log_xlsx` (`4337`), `_import_records_xlsx`
(`4357`).

**`_import_records_xlsx` belongs here, and 046's table puts it in the wrong cluster.** 046
lists it as the first member of its "lookup import and proposals" row, at `4313`. Reading
it at `4357` settles it the other way: its docstring is "Restore records from an .xlsx
archive (appends, new ids)", it reads `_ARCHIVE_COLS`, and it is the exact counterpart of
`_export_records_xlsx` twenty lines above it under the same Archive banner. It imports
*records* - transactions - not assets, and has nothing to do with the asset lookup sheet or
with proposals. Taking it with the archive leaves both this cluster and 055's contiguous;
leaving it behind splits a banner across two tickets for the sake of a name.

**Which means this ticket inherits 046's rule-6 warning, and 055 does not.** 046 wrote
that `_import_records_xlsx` "was already named in 039's finding as the second writer into
`transactions` that rule 6 does not yet enforce", and told whoever files that cluster's
ticket to expect `register_transactions.py` (042) in its Depends-on line. That warning
travels with the function, so it is on this ticket's line and not on 055's. **This ticket
does not fix rule 6** - out of scope in 039, out of scope in 046, and out of scope here.
It moves a function that has the problem; the problem stays exactly as visible as it is
today, which is the point of saying so.

## Scope

One new module, `server_archive.py`, beside `server.py`.

1. **Move `server.py:3795-4407` verbatim.**
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason. `_import_records_xlsx` writes into `transactions`; whether it reaches
   `register_transactions` through `bind()` or keeps writing SQL inline is a question of
   what the current code does, not of what it should do - move it as it is.
3. **`server.py` imports it at module level and binds it** in the existing block
   (`server.py:7357-7430`), then imports the moved names back flat, so `server_gui.py`'s
   `backup_restore` and `manage_records` windows resolve unchanged.

## Not in this ticket

- **Rule 6's second enforcement point.** `_import_records_xlsx` does not route through
  `_create_transaction`; it did not before this ticket and it does not after. That is its
  own ticket, and this one must not quietly become it.
- `migrations/` itself, or any migration file. The helpers that run them move; the
  migrations do not.
- ADR-0019's backup format, the manifest, or what a restore verifies.
- The `/records/import` route (`server.py:6356`), which stays in `server.py`.

## Sequencing

046's six all rewrite `tools/package.ps1:149`, one line, so they are a chain rather than
six independent tickets: 050, 051, 052, 053, 054, 055, merged in that order, one at a
time. The code in most of them is independent; the line is not. This is the same reason
035 and 036 were sequenced, and the reason 041 had to land before 042 and 043.

## Cascade

The set 043 paid for `register_engineers.py`, re-found against this tree rather than
copied from 046:

- `CLAUDE.md`'s files table - a row for the new module.
- `docs/reference/architecture.md`'s table - the same row, at the length that table's
  rows run to.
- `docs/CODING_STANDARDS.md` "Where code goes" (`docs/CODING_STANDARDS.md:12`, the module
  list at `:41`) and the sentence at `:91` naming the modules `server.py` imports.
- **`tools/package.ps1:149` `$SourceFiles`** - one line, and **all six of 046's tickets
  rewrite it**. This is the trap `docs/agents/ticket-workflow.md` "Two tickets that
  cascade to the same line" describes, and the reason 035 and 036 were sequenced over the
  same line. The six are a chain, merged one at a time, never two in parallel.
- `tools/server-checks.py:141-143`, the staging tuple, which carries seven names today; a
  `*_SRC` read beside `ENG_SRC` (`tools/server-checks.py:242`) if any group asserts
  against the module's own source; and the reload block at
  `tools/server-checks.py:9701-9745`, which pops and restores `register_engineers` by
  name and needs the same for this module if a group re-imports `server.py`.
- `tools/gate.py`'s `MAP` (`tools/gate.py:85-90`) - a row tagged `("server",)`, or an edit
  to the new file runs no gate at all, the failure `gate.py`'s own docstring names.
- `tools/cascade-audit.py` - `SHIPS` (`:1448`), `BESIDE_MODULES` (`:1563`), `_FIT_APPS`
  (`:1657`) and `_EVENT_SOURCES` (`:1877`). Check each against this module rather than
  copying four bullets forward: `SHIPS` yes, the file rides in the server payload;
  `_EVENT_SOURCES` only where the moved block calls `_log_event`, which is a grep and not
  an assumption; `_FIT_APPS` counts windows and a server module draws none.
- **Not** `installer.py`'s `SOURCE_FILES`, and **not** `tools/bundle-client.ps1`. Both are
  the client payloads; a server module ships in neither, which is what makes this cascade
  shorter than 044's and 045's.

Specific to this ticket:

- `_migrate_cli` (`3943`) is a command-line entry point. Grep for what invokes it -
  `server.py`'s own `__main__` dispatch, `docs/runbooks/` and `tools/` - before moving it,
  and check `docs/reference/database.md`'s migration section still describes where it
  lives.
- `docs/reference/database.md` - the schema block and the migration prose both point at
  `server.py` for `run_migrations`.
- `_EVENT_SOURCES` needs it: `_take_backup`, `_restore_backup` and `_import_records_xlsx`
  each log events with rows in `docs/system-log-events.md`.
- `docs/runbooks/release.md` - check whether it names `server.py` as where backup or
  migration lives.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- Take a backup and restore it into a scratch database, and confirm
  `_verify_backup` still passes on it.
- Run a migration from an older schema version and confirm the version lands where
  `docs/reference/database.md` says.
