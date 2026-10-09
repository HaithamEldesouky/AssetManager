# 103 - An asset has a numeric Asset Number, a Serial Number and a Type

**Type:** bug fix · **Depends on:** none · **Issue:** [#279](https://github.com/HaithamEldesouky/AssetManager/issues/279)

## Finding

The Storekeeper's Add New Asset dialog took `11` / `11` / Mobile and also took an
Asset Number with letters in it and a proposal with no Serial Number. Three defects,
one rule:

1. **Nothing says an Asset Number is digits only.** Every door into the register
   accepts `P-1`. The embedded sheet (`DEFAULT_LOOKUP_B64`, 3462 rows) holds digits
   only in every Asset Number and a Serial Number on every row, so the department's
   real data already has the shape; no door holds it to that shape.
2. **One identifier is enough.** `_save_asset` (`register_assets.py`),
   `_propose_asset` and `_validate_import_rows` (`server_lookup.py`) and the sync
   reconcile (`server_sync.py`) all refuse only when *both* identifiers are
   missing - rule 5's shape, which is a Transaction's rule, applied to an asset.
   An asset needs all three of Asset Number, Serial Number and Asset Type. Asset
   Model stays optional.
3. **The dialog cannot show its own refusal.** `ui_kit.fit(dlg, 430)` sizes the
   window once, with the `say` label empty; `resizable(False, False)` then clips
   any refusal to its first line. The `already_proposed` sentence is cut mid-word.

Uniqueness is already held - the register (`duplicate_identifier`) and pending
proposals (`already_proposed`), case not significant - and is not changed here.

## Scope

1. **One rule, worded once.** `register_assets.py` gains `_asset_shape_error(an, sn,
   at)`: `""` when the three fields describe an asset, otherwise the sentence saying
   which one does not. Asset Number digits only means ASCII `0-9`
   (`re.fullmatch("[0-9]+", ...)`), not `str.isdigit`, which takes `²`.
2. **Every door calls it.**
   - `_save_asset` - Manage Assets add and edit, a proposal's approval, the Admin
     import, `POST /lookup/upload`, the sync's writes. Raises `ValueError` as now.
   - `_propose_asset` - `_AssetRefused(..., "bad_asset")`, 400, as now.
   - `_validate_import_rows` - the row's `error`, so the Admin importer and the
     Storekeeper's Import Asset List show every failing row with its reason and the
     person fixes the file; nothing is dropped silently.
   - The sync reconcile - a failing record goes to `report["skipped"]` with its
     reason, including a matched row whose merged fields would fail, rather than
     letting `_save_asset` roll back the whole run.
   - `_replace_assets` - still all or nothing, but refuses with **every** failing
     row listed rather than the first.
3. **The dialog shows what the server said.** `storekeeper_propose.py` drops its
   own copies of the checks (rule 6: the server validates) and calls
   `ui_kit.fit(dlg, 430)` again after writing `say`, so the window grows to the
   refusal.
4. **Checks.** `tools/server_checks/` fixtures that write assets with letters in
   the Asset Number or no Serial Number are brought to the rule; new cases for a
   letter, a `²`, a missing serial and a missing type at each door, the sync's
   skip and the upload's full list.

## Not in this ticket

- Transactions. Rule 5 (at least one identifier) is about what a Transaction
  carries; a Transaction still resolves against the register (rule 6).
- Rows already in a live register that fail the rule. They keep resolving for
  Transactions; an Admin editing one in Manage Assets is refused until it is
  fixed. No migration.
- `_seed_assets_if_empty` - its only input is the embedded sheet, which conforms.
- Leading zeros: `011` and `11` stay two Asset Numbers, compared as text.

## Cascade

- `CONTEXT.md` - Asset Number and Serial Number: every asset carries both, the
  Asset Number is digits only.
- `docs/reference/api.md` - `/assets/propose`, `/assets/import/preview`,
  `/lookup/upload` rows.
- `docs/reference/apps.md` - the Storekeeper's Proposing an asset and Proposing a
  whole delivery bullets; the console's Lookup Sheet bullet where it states the rule.
- ADR-0011, ADR-0012, ADR-0014 - re-read; amend only a sentence this makes false.
- `APP_VERSION` patch bump, all four sources.
