# 053 - The System Log becomes a module

**Type:** refactor · **Depends on:** 052 · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#227](https://github.com/HaithamEldesouky/AssetManager/issues/227)

## Finding

The fourth of 046's six, re-derived against the 9,826-line tree 043 left. 046 said this
cluster and 054's "read across several tables and should be read again once the others
have landed"; that is why it is fourth rather than first.

- `# ─── The System Log ───` - `server.py:7033`.
- The cluster ends at `7679`, immediately before `# ─── Mail ───` at `7680`.

046 said `8060-8458`, 399 lines. It is 647, and **it is not contiguous** - which 046's
table does not say and could not have known.

**The `bind()` block sits inside it.** `server.py:7357-7430` is where `server_cert.bind()`,
`register_assets.bind()`, `register_transactions.bind()`, `register_engineers.bind()` and
`server_gui.bind()` are called, together with the flat imports back from `server_gui`. It
is there rather than beside the imports for the reason its own comment at `7357-7360`
gives: the helpers it hands over - `_log_event` at `7291` above it, and 052's four queue
and client readers - do not exist at the top of the file. So the cluster is two runs:

- **`7033-7356`** - the `EVENT_SENTENCES` table and the banner, `event_phrase` (`7265`),
  `event_sentence` (`7270`), `_log_event` (`7291`).
- **`7431-7679`** - `_log_event_names` (`7433`), `_log_rows` (`7453`), `_log_entry`
  (`7483`), `_log_client` (`7500`), `_log_diff` (`7536`), `_log_clear` (`7568`),
  `_record_log` (`7592`), the `POST /clients/log` route (`7631`), `_log_trim` (`7644`),
  `_log_retention_loop` (`7670`).

324 + 249 = **573 lines** moved, with the 74-line `bind()` block staying exactly where it
is. Moving `_log_event` out from above that block is the whole difficulty of this ticket
and the reason it is not a mechanical cut: every `bind()` call below it is handed
`_log_event`, so after the move `server.py` must import it back from the new module
*before* line `7357`, and the new module must not need anything defined after `7357` at
import time.

**`_log_event` calls `_notify_of` at `server.py:7349`**, which 050 moves into
`server_mail.py`. With 050 landed first, that call reaches across `bind()`. Confirm it
does before writing anything else - it is the one line that couples this cluster to
another of the six.

**`_log_event` is what every other module logs through.** `register_assets`,
`register_transactions`, `register_engineers` and `server_cert` each take it through their
own `bind()`. Their bindings must be handed the same function object after the move, not a
re-export that shadows it.

## Scope

One new module, `server_log.py`, beside `server.py`.

1. **Move `server.py:7033-7356` and `7431-7679` verbatim.** The `bind()` block
   (`7357-7430`) does not move.
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason.
3. **`server.py` imports it and binds it before the existing `bind()` block**, not inside
   it - `_log_event` has to exist by line `7357` for the five calls there to be handed it.
   Then the moved names come back flat, so `server_gui.py`'s `system_log` window and
   `tools/server-checks.py`'s direct calls resolve unchanged.

## Not in this ticket

- `POST /clients/log`'s shape, or any `docs/reference/api.md` row. The route moves or
  stays as one judgement, but what it accepts and answers does not change.
- Any new or renamed event. A renamed `_log_event` call cascades into
  `docs/system-log-events.md` **and** `EVENT_SENTENCES`, per `CLAUDE.md`'s table; this
  ticket renames none.
- Retention policy or the trim window.

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

Specific to this ticket, and the reason it is the widest of the six:

- **`EVENT_SENTENCES` moves file.** `CLAUDE.md`'s cascade table has a row reading "a
  `_log_event` call | its row in `docs/system-log-events.md` **and** its phrase in
  `EVENT_SENTENCES` in `server.py`". That row names `server.py` by name and must name the
  new module instead. `tools/cascade-audit.py` is the gate on it - find what reads
  `EVENT_SENTENCES` there before moving it.
- `tools/cascade-audit.py:1877` `_EVENT_SOURCES` - the tuple of files scanned for
  `_log_event` calls. The new module joins it, and every other file in it keeps its place.
- `docs/system-log-events.md` - check whether any sentence in it names `server.py` as
  where an event is raised.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- Read the System Log window in the Server GUI and confirm the sentences
  are unchanged, `EVENT_SENTENCES` having moved file.
- Raise one event of each component and confirm `_notify_of` still fires through 050's
  module.
