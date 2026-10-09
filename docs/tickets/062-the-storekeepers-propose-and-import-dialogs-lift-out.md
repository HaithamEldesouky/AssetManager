# 062 - The Storekeeper's propose and import dialogs lift out

**Type:** refactor · **Depends on:** 061 (sequence after the 2.6.0 release) · **Found by:** modularisation review, Sep 2026 · **Issue:** [#237](https://github.com/HaithamEldesouky/AssetManager/issues/237)

## Finding

`storekeeper_app.py` is 3,754 lines (measured before 061 lands; re-measure once it has,
since 061 removes 373 lines ahead of this one - `storekeeper_app.py:182-188` and
`:2717-3082`). Grep for the propose/import surface
(`grep -nE '^\s{4}def (_propose_dialog|_read_import_file|_import_proposals_dialog|_import_proposals_window)' storekeeper_app.py`)
finds four methods, contiguous with nothing else interleaved
(`grep -nE '^\s{4}def ' storekeeper_app.py` between 1819 and 2333 returns exactly these
four): `_propose_dialog` (`:1819`), `_read_import_file` (`:2007`),
`_import_proposals_dialog` (`:2040`), `_import_proposals_window` (`:2064`), ending at
`:2332` immediately before `_seen_decided_load` (`:2333`, unrelated - the seen/decided
persistence for the Notifier's popup queue). Block: `1819-2332`, 514 lines - the "~530"
this ticket was filed against, close enough that no further reconciliation is needed.

Both dialogs work the Storekeeper's proposal flow (ADR-0012): `_propose_dialog` is what
opens when neither identifier resolves against the lookup sheet (rule 6); the three
`_import_*` methods are the file-borne version of the same proposal, `#029`'s addition.

## Scope

One new module, `storekeeper_propose.py`, beside `storekeeper_app.py`, sequenced after
061 so both new modules exist side by side rather than one being written against a
`storekeeper_app.py` the other has already changed underneath it.

1. **Move `storekeeper_app.py:1819-2332` verbatim** - the four methods above - into
   `storekeeper_propose.py`.
2. **Same seam as 061, for the same reason**: these are methods of `StorekeeperApp`, not
   free functions, and the block reaches a comparable spread of `self.<name>` attributes
   (the server URL, the lookup cache, the pending-proposal state, the widgets each dialog
   builds). Grep every `self.<name>` inside `1819-2332` before finalising the constructor,
   the same way 061's Scope §2 requires. Build the same shape 061 built - a class taking
   the app object (`ProposeDialogs(app)` or equivalent) rather than either enumerating every
   attribute as a parameter or leaving the coupling unstated - and say why, matching
   whichever of the two arguments 061 actually settled on rather than re-deciding it
   independently; a different seam for two siblings moved out of the same class in the same
   week would be its own inconsistency.
3. **`storekeeper_app.py` imports `storekeeper_propose`** at module level and calls its
   entry points (`_propose_dialog`'s replacement, and the import menu's replacement for
   `_import_proposals_dialog`) wherever they were called from today.

## Not in this ticket

- Any change to what a propose or import dialog does, its layout, or its wording. A move,
  not a redesign.
- 061's own scope (the Bulk window) - this ticket depends on it only because both edit
  `storekeeper_app.py` and the same cascade lines; sequence behind it, do not fold the two
  together.
- `_seen_decided_load`/`_seen_decided_save`/`_init_seen_decided` (`:2333` onward) - these
  read/write which proposal decisions the Notifier has already shown, not the propose/import
  surface itself, and stay in `storekeeper_app.py`.

## Cascade

Same lines as 061, all in the state 061 leaves them:

- `tools/bundle-client.ps1:123` `$Apps.storekeeper.Extra` - gains `storekeeper_propose.py`
  beside `storekeeper_export.py` and (after 061) `storekeeper_bulk.py`. Not `$Payload`
  (`:136`) - same reasoning 061 and `#219` gave.
- `installer.py:59-61` `SOURCE_FILES` - the storekeeper entry gains `storekeeper_propose.py`.
- `tools/dev-run.ps1:296` `$StorekeeperOwn` - gains `storekeeper_propose.py`.
- `tools/client-checks.py:197,216` - both the staging tuple and `SRC_FILES` gain
  `storekeeper_propose.py`.
- `tools/gate.py:99` `MAP` - the alternation gains `storekeeper_propose`.
- `tools/cascade-audit.py` `_FIT_APPS` (`:1763`) - the `"Storekeeper"` tuple gains
  `storekeeper_propose.py`, since `_propose_dialog` and the import window both call
  `ui_kit.fit`.
- `tools/cascade-audit.py` `_EVENT_SOURCES` (`:1983`) - grep the moved block for
  `_log_event` calls (a proposal being created or imported is a plausible System Log event -
  check rather than assume) and add the module if any are found.
- `CLAUDE.md` "The files" table - the `storekeeper_app.py` row's description narrows
  further (now describing what stays after both 061 and this ticket); a
  `storekeeper_propose.py` row is added.
- `docs/reference/architecture.md` and `docs/reference/apps.md` - the same, in full;
  `apps.md`'s Storekeeper section names which file owns Propose and Import.

## Verification

- `ast.parse()` both files.
- Headless import of `storekeeper_app.py` with no display.
- `py -3.12 tools/gate.py --all`.
- `py -3.12 tools\client-checks.py` green.
- Open the Propose dialog by hand (submit a transaction with neither identifier in the
  lookup) and the Import dialog (import a proposals file) against a running server - the
  four methods named in Finding, once each.
