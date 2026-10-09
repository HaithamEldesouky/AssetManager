# 055 - The lookup import and the proposals become a module

**Type:** refactor · **Depends on:** 054, 041, 042 · **Found by:** 046 (#220), re-derived Sep 2026 · **Issue:** [#229](https://github.com/HaithamEldesouky/AssetManager/issues/229)

## Finding

The last of 046's six, re-derived against the 9,826-line tree 043 left - and the one 046
singled out as "not a clean move".

**It is cleaner than 046 expected, in one respect and not the other.** 046 listed it as
four scattered functions, "interleaved with the Assets cluster 041 already moved out from
around them, not contiguous". With 041 landed, what is left is one contiguous block:

- `# ─── Lookup helpers ───` - `server.py:4408`.
- The block ends at `5176`, immediately before `# ─── Routes ───` at `5177`.

5176 - 4408 + 1 = **769 lines**: `_ensure_sample_lookup` (`4410`), `_xlsx_asset_rows`
(`4428`), `_lookup_xlsx_bytes` (`4463`), `_seed_assets_if_empty` (`4498`), `_import_key`
(`4580`), `_map_import_columns` (`4585`), `_check_import_mapping` (`4612`),
`_import_file_rows` (`4638`), `_validate_import_rows` (`4665`), `_import_assets` (`4778`),
`class _AssetRefused` (`4804`), `_load_proposals` (`4833`), `_propose_asset` (`4851`),
`_propose_batch` (`4953`), `_decide_proposal` (`5017`), `_replace_assets` (`5079`),
`_load_lookup_table` (`5117`), `_asset_models` (`5142`), `_lookup_asset_types` (`5168`).

Three of 046's four anchors are in it - `_validate_import_rows` (`4665`, 046 said `4744`),
`_load_proposals` (`4833`, said `4912`), `_load_lookup_table` (`5117`, said `5196`). **The
fourth is not.** `_import_records_xlsx` (046 said `4313`, now `4357`) is the archive's
record import, not the lookup's asset import; 054's Finding gives the reading that settles
it, and it moves with the archive. 046's rule-6 warning travels with that function, so it
is on 054's line rather than this one.

**What makes this the hardest of the six is not the span, it is the coupling.** This block
is the asset lookup's write path, and 041 moved the `assets` table's four functions into
`register_assets.py` from around it. `_import_assets`, `_replace_assets`, `_propose_asset`,
`_propose_batch` and `_decide_proposal` all write assets; `_load_lookup_table`,
`_asset_models` and `_lookup_asset_types` all read them. Grep every call from this block
into `register_assets` and `register_transactions` before writing `bind()`'s signature -
that count is what decides whether this is a module beside the registers or a second
interface onto them, and it is the question 046 said to expect.

**Rule 2 and rule 11 both live here.** `GET /asset_types` serves the distinct `asset_type`
values of the `assets` table, and `DEFAULT_LOOKUP_B64`'s two update doors are
admin-password only. Neither changes; both must still be true after the move, and
`tools/server-checks.py` asserts them.

## Scope

One new module, `server_lookup.py`, beside `server.py`.

1. **Move `server.py:4408-5176` verbatim.**
2. **It reaches back through `bind()`, and never imports `server`.** `applaunch.py` runs
`server.py` as `__main__` through `runpy.run_path`, so `import server` from inside the
new module executes the whole server a second time rather than reaching the one running -
the reason `server_cert.py` set this pattern and `register_assets`,
`register_transactions`, `register_engineers` and `server_gui` all repeat it. Build the
handed-over name list with a `symtable` sweep over the moved block rather than by hand:
036's "How it landed" note found fourteen names 035's hand-written plan had missed, and
045 built its list that way for that reason. Expect this module's bound list to be the longest of the six, for the
   coupling the Finding describes.
3. **`server.py` imports it at module level and binds it** in the existing block
   (`server.py:7357-7430`), then imports the moved names back flat, so the routes at
   `8699-9023` - `/lookup`, `/asset_types`, `/asset_models`, `/lookup/file`,
   `/lookup/upload`, `/assets/propose`, `/assets/import/preview`, `/assets/proposals`,
   `/assets/proposals/decide` - and `server_gui.py`'s `manage_assets` and
   `asset_proposals` windows resolve unchanged.

## Not in this ticket

- **Any move of a function into `register_assets.py` or `register_transactions.py`.** This
  block reaches into both; reaching is not belonging, and redrawing that boundary is a
  ticket of its own. If the grep in Scope §2 says it should be, write that ticket rather
  than doing it here.
- `DEFAULT_LOOKUP_B64` (rule 11) and the two doors that update it.
- The nine routes listed above, which stay in `server.py`.
- Proposal approval policy (ADR-0017) or what `_validate_import_rows` accepts.

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

- `_EVENT_SOURCES` needs it - `_import_assets`, `_decide_proposal`, `_propose_asset` and
  `_replace_assets` all log events, with rows in `docs/system-log-events.md`.
- `docs/reference/apps.md` - the Manage Assets and Asset Proposals sections describe
  windows whose helpers live here.
- `CLAUDE.md` rules 2 and 11 name `server.py` for the lookup. Read both sentences after
  the move and check each still holds; rule 11 says the workbook is embedded **in
  `server.py`**, which stays true only if `DEFAULT_LOOKUP_B64` does not move.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `server.py` headless and confirm it still imports.** The `bind()` pattern's one
  real failure mode is a name handed over after something has already read it.
- `py -3.12 tools\server-checks.py` green, and the same "N check group(s), M
  assertion(s)" line as a run on `main` before the branch - a move changes no assertion.
- `GET /asset_types` and `GET /asset_models` against a running server, and
  check the responses are what they were (rule 2).
- Import an asset file with the columns mapped by hand, and approve a Storekeeper proposal
  from the Server GUI - the two write paths this block owns.
