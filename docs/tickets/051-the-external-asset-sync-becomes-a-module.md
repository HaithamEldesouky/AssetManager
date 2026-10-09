# 051 - The external asset sync becomes a module

**Type:** refactor · **Depends on:** 050 (cascade lines only) · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#225](https://github.com/HaithamEldesouky/AssetManager/issues/225)

## Finding

The second of 046's six, re-derived against the 9,826-line tree 043 left rather than
copied from 046's table.

- `# ─── The external asset system ───` - `server.py:8146`.
- The block ends at `8698`, immediately before `# ─── Lookup routes ───` at `8699`.

8698 - 8146 + 1 = **553 lines**, one contiguous run: `_sync_secret_set` (`8205`),
`_sync_secret_get` (`8211`), `_sync_secret_stored` (`8216`), `_sync_cfg` (`8221`),
`_sync_url` (`8254`), `_sync_fetch` (`8262`), `_sync_keys` (`8361`), `_sync_mapping`
(`8377`), `_sync_rows` (`8406`), `_sync_reconcile` (`8419`), `_sync_summary` (`8546`),
`_sync_names` (`8555`), `_sync_run` (`8563`), `_sync_last_run` (`8649`), `_sync_loop`
(`8675`). 046 said `8955-9451`, 497 lines.

**046's table is wrong about `_sync_admin_cfg`, and this is the correction.** It lists
`_sync_admin_cfg` as this cluster's isolated first line, at `2659`. It is now at
`server.py:2703`, and reading it shows it has nothing to do with the external asset
system: it re-reads `admin_config.json` where a second process has written it - ADR-0001's
IIS deployment and the Windows Service, where the Server GUI is monitor-only and Change
Admin Password wrote a hash the serving process never saw. It is an admin-credential
helper sharing a `_sync_` prefix with this cluster and nothing else. **It stays in
`server.py`.** 046 grouped it by name; this ticket groups it by what it does, which is
what 046 asked for when it called its table a starting point for a grep rather than a
citation for one.

**It needs two names 050 leaves behind.** `_sync_secret_set` (`8207`) and
`_sync_secret_get` (`8213`) call `_secret_set` (`7727`) and `_secret_get` (`7766`), the
generic pair 050 deliberately does not move. Both come over through `bind()`.

## Scope

One new module, `server_sync.py`, beside `server.py`.

1. **Move `server.py:8146-8698` verbatim.** `_sync_admin_cfg` (`2703`) does not move.
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason. Expect `_secret_set`, `_secret_get`, `get_db`, `_log_event` and the
   register functions `_sync_reconcile` writes through to be among the names - confirm
   that by sweep; do not take this sentence as the list.
3. **`server.py` imports it at module level and binds it** in the existing block
   (`server.py:7357-7430`), then imports the moved names back flat, so `server_gui.py`'s
   `asset_sync` window and `_start_background_jobs` (`server.py:9596`), which starts
   `_sync_loop`, resolve unchanged.

## Not in this ticket

- `_sync_admin_cfg` (`server.py:2703`), for the reason the Finding gives.
- `_secret_set` / `_secret_get` - 050's Not-in-this-ticket, and the same answer here.
- Any change to the mapping, the reconcile rules or the transport. ADR-0014 settles what
  this cluster does; this ticket moves it.
- The Sync window in `server_gui.py`.

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

Specific to this ticket: `_EVENT_SOURCES` needs it - `_sync_run` and `_sync_reconcile`
log events, and `docs/system-log-events.md` holds their rows. `_start_background_jobs`
(`server.py:9596`) names `_sync_loop` and stays in `server.py`.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- Run a sync against the stubbed transport ADR-0014 describes, and confirm
  the report and the System Log row read as they did before the move.
