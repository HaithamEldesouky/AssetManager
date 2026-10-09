# 052 - The client registry and its commands become a module

**Type:** refactor · **Depends on:** 051 (cascade lines only) · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#226](https://github.com/HaithamEldesouky/AssetManager/issues/226)

## Finding

The third of 046's six, re-derived against the 9,826-line tree 043 left.

- `# ─── Clients (the registry of installations) ───` - `server.py:6396`.
- The block ends at `7032`, immediately before `# ─── The System Log ───` at `7033`.

7032 - 6396 + 1 = **637 lines**, contiguous. 046 said `7217-8059`, 843 lines; the cluster
is 206 lines smaller than its table claims as well as 800 lines higher up.

Helpers: `_record_checkin` (`6416`), `COMMANDS` (`6553`, and 046 put it at `7354`),
`_command_status` (`6602`), `_queue_command` (`6618`), `_command_rows` (`6720`),
`_client_rows` (`6735`), `_age_choice_label` (`6755`), `_stale_clients` (`6766`),
`_clear_stale_clients` (`6789`). Routes, in the same run: `POST /clients/checkin`
(`6856`), `GET /clients` (`6871`), `POST /clients/command` (`6924`), `POST
/clients/push_cert` (`6965`), `POST /clients/clear` (`6995`).

**This cluster is the one of the six whose routes sit inside it**, rather than down in the
Routes section with the rest. 041-043 each left their routes in `server.py` and moved only
the functions behind them; doing the same here means the move is `6396-6855` and the five
routes stay, which is the shape the other five tickets in this chain take and the shape
`server_gui.py` and `tools/server-checks.py` already reach through. Splitting the banner
that way is the one judgement call this ticket has to make - make it explicitly, and say
which way in the commit.

**`server_cert.bind()` reads four names from here.** The comment at `server.py:7357-7360`
says so: it sits where it does "because the helpers below it - `_log_event` above, and the
four queue and client readers before it - do not exist yet at the top of the file". Those
four are this cluster's. After the move they are bound from the new module rather than
defined above the block, so `server_cert.bind()`'s arguments change source without
changing shape.

## Scope

One new module, `server_clients.py`, beside `server.py`.

1. **Move `server.py:6396-6855` verbatim** - the banner through `_clear_stale_clients`,
   stopping before `@app.route('/clients/checkin')` at `6856`. The five routes
   (`6856-7032`) stay in `server.py` and call into the module.
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason.
3. **`server.py` imports it at module level and binds it** in the existing block
   (`server.py:7357-7430`), then imports the moved names back flat. Confirm
   `server_cert.bind()`'s four queue and client readers still resolve - they are the one
   documented cross-cluster reader and the comment naming them is at `7357-7360`.

## Not in this ticket

- The five `/clients*` routes, per Scope §1.
- `ADR-0020`'s certificate push. `POST /clients/push_cert` (`6965`) is a route in this
  span and stays; `server_cert.py` is untouched.
- Connected Clients in `server_gui.py`.
- Any change to the check-in shape, the command vocabulary (`COMMANDS`, `6553`) or the
  stale-client window. A move.

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

Specific to this ticket: `_EVENT_SOURCES` needs it - `_queue_command` and
`_clear_stale_clients` log events, with rows in `docs/system-log-events.md`.
`docs/reference/api.md`'s rows for the five `/clients*` endpoints are **unchanged**: the
routes do not move and neither does any credential or response shape.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- Hit `GET /clients` against a running server and check the response is
  what it was, per `CLAUDE.md`'s "Before you call a change done".
- Queue a command from Connected Clients and confirm a client still collects it.
