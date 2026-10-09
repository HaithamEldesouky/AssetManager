# 061 - The Storekeeper's bulk window lifts out

**Type:** refactor · **Depends on:** nothing (sequence after the 2.6.0 release) · **Found by:** modularisation review, Sep 2026 · **Issue:** [#236](https://github.com/HaithamEldesouky/AssetManager/issues/236)

## Finding

`storekeeper_app.py` is 3,754 lines. Grep for the bulk surface
(`grep -nE '^\s*def (_bulk_|_open_bulk_window)' storekeeper_app.py`) finds eight matches,
but only seven are methods of `StorekeeperApp`:

- `_bulk_tags(tree)` - `storekeeper_app.py:182`, a **module-level** helper (no `self`),
  defined just above `class StorekeeperApp` (`:194`) beside `_round_rect`/`Pill`. It tags
  the bulk tree's two colours and is called once at definition time in its own
  `_retint_hook` closure (`:187`) and once from inside the class, `_bulk_tags(self._bulk_tree)`
  at `:2839`. It is used only by the bulk window and by nothing else in the file.
- `_open_bulk_window` (`:2717`) through `_bulk_submit_all` (`:2946-3082`) - seven methods,
  contiguous, no other method interleaved (`grep -nE '^\s{4}def ' storekeeper_app.py` in
  the 2717-3084 range returns exactly these seven, then `_paint_sk_name` at `:3084`, which
  is not part of the bulk surface): `_open_bulk_window`, `_bulk_add_from_entry`,
  `_bulk_got_lookup`, `_bulk_remove_selected`, `_bulk_clear_queue`, `_bulk_paint`,
  `_bulk_submit_all`. The block runs `2717-3082`, 366 lines.

Total: 366 lines of methods plus the 7-line module helper `_bulk_tags`, both moving
together since the helper exists for nothing else.

## Scope

One new module, `storekeeper_bulk.py`, beside `storekeeper_app.py`.

1. **Move `_bulk_tags` (`:182-188`) and the seven `_open_bulk_window`/`_bulk_*` methods
   (`:2717-3082`) verbatim** into `storekeeper_bulk.py`.
2. **The seam is a class taking the app, not the methods restated as free functions taking
   `self`.** These are methods of `StorekeeperApp`, so `self` inside them reaches roughly
   forty other attributes (`self.server_url`, `self.cfg`, `self._bulk_queue`,
   `self._bulk_tree`, widgets it builds on the fly, `_refresh_transactions`, and more) -
   grep every `self.<name>` inside the moved block before finalising the constructor's
   surface, since guessing it short is the same silent-break shape `#218`'s ticket warned
   against for `N.<name>`. Prefer **`class BulkWindow` taking the app object itself as its
   one constructor argument** (`BulkWindow(app)`, called from `StorekeeperApp` as
   `storekeeper_bulk.BulkWindow(self).open()` or equivalent) over either passing `self`
   whole as an untyped bag *or* enumerating every one of those forty attributes as separate
   parameters:
   - Enumerating them is `#218`'s and `#219`'s `N.<name>`/`S.<name>` shape bent out of
     shape - those reach a **module**, whose surface is worth writing down explicitly
     because a module is imported once and reused from everywhere; a constructor called
     once per window opening gains nothing from spelling out forty positional names, and
     loses the ability to reach a fifty-first attribute the mover didn't think to grep for
     without a second ticket.
   - Passing `self` whole and reading `app.<anything>` from inside `BulkWindow` is honest
     about the coupling this block actually has - the bulk window was never independent of
     `StorekeeperApp`, it is a `StorekeeperApp` behaviour that happened to live inside the
     class body - and it keeps the diff a verbatim move (`self.` becomes `app.` by a
     mechanical rewrite, the same shape a `symtable` sweep gave `#218` and `#222`) rather
     than a redesign that invents a narrower interface this ticket was not asked to design.
   - State in the PR which was built and why, since "prefer the class with explicit
     arguments" in this ticket's title is the default the author should defend departing
     from if the forty-attribute count turns out smaller once grepped, not a instruction to
     enumerate forty parameters regardless of what grepping finds.
3. **`storekeeper_app.py` imports `storekeeper_bulk`** at module level and calls
   `storekeeper_bulk.BulkWindow(self).open()` (or the chosen entry point) wherever
   `_open_bulk_window` was called from the tray/menu today.

## Not in this ticket

- Any change to what the Bulk window does, its layout, or its wording. A move, not a
  redesign.
- `#194`/`#201`'s popup timers, `_propose_dialog`, `_import_proposals_dialog` or any other
  Storekeeper window - only the bulk surface named in Finding.
- Deciding a narrower interface than "the app" for `BulkWindow` - see Scope §2's "prefer
  the class" discussion; a follow-up ticket that shrinks the constructor to only the
  lookup/submit/config callables the class actually needs is a separate, smaller change,
  not implied by this one.

## Cascade

- `tools/bundle-client.ps1:123` - `storekeeper_export.py` is `$Apps.storekeeper.Extra`
  today (`Extra = @("storekeeper_export.py")`, `#219`'s exact shape); add
  `storekeeper_bulk.py` to the same list, not to `$Payload` (`:136`) - `storekeeper_bulk.py`
  ships only where `storekeeper_app.py` does, the same distinction `#219`'s ticket drew for
  `notifier_remote.py`/`storekeeper_export.py`.
- `installer.py:59-61` `SOURCE_FILES` - the storekeeper entry already carries
  `storekeeper_export.py`; add `storekeeper_bulk.py` beside it.
- `tools/dev-run.ps1:296` `$StorekeeperOwn = @("storekeeper_app.py",
  "storekeeper_export.py")` - gains `storekeeper_bulk.py`.
- `tools/client-checks.py:197,216` - the staging loop's tuple (`APPS + ("common.py",
  "ui_kit.py", "ui_glass.py", "client_update.py", "applaunch.py", "notifier_pending.py",
  "notifier_remote.py", "storekeeper_export.py")`) and `SRC_FILES = APPS +
  ("notifier_remote.py", "storekeeper_export.py")` both gain `storekeeper_bulk.py`, or the
  staged Storekeeper fails its own import and the size groups stop reading the bulk
  window's source text.
- `tools/gate.py:99` `MAP` - the existing row
  `r"^(storekeeper_app|storekeeper_export|notifier_app|notifier_pending...)\.py$"` gains
  `storekeeper_bulk` to the alternation, or an edit to the new module runs no gate.
- `tools/cascade-audit.py` `_FIT_APPS` (`:1763`) - the `"Storekeeper"` tuple
  (`("storekeeper_app.py", "storekeeper_export.py")`) gains `storekeeper_bulk.py`, since the
  Bulk window's own `ui_kit.fit` calls move with it.
- `tools/cascade-audit.py` `_EVENT_SOURCES` (`:1983`) - grep the moved block for
  `_log_event` calls before assuming none; `storekeeper_export.py` is absent from this
  tuple today because it logs no event, so check the bulk block the same way rather than
  copying that absence forward.
- `CLAUDE.md` "The files" table - the `storekeeper_app.py` row's description narrows to
  what stays; a `storekeeper_bulk.py` row is added.
- `docs/reference/architecture.md` and `docs/reference/apps.md` - the same, in full;
  `apps.md`'s Storekeeper section names which file owns the Bulk window, the same way it
  already names `storekeeper_export.py` for the Export window since `#219`.

## Verification

- `ast.parse()` both files.
- Headless import of `storekeeper_app.py` with no display.
- `py -3.12 tools/gate.py --all`.
- `py -3.12 tools\client-checks.py` green.
- Open the Bulk window by hand against a running server: add an entry, scan a lookup hit,
  remove a queued row, clear the queue, and submit - the seven methods named in Finding,
  once each.
