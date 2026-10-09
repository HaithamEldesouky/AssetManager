# 004 - Server GUI: Add Transaction gets the Storekeeper's lookup auto-resolve

**Type:** enhancement · **Depends on:** nothing

## What is asked

Add Transaction in the Server GUI should resolve an asset from the lookup sheet as it is
typed, the way the Storekeeper's form does.

## Where it stands today

`add_transaction()` (`server.py` ~6212) builds plain `tk.Entry` fields for Asset Number and
Serial Number and a full `_lookup_asset_types()` picker for the type. Nothing is looked up
until submit, where `_create_transaction` corrects the three fields from the sheet or
refuses with `not_in_lookup` - so the admin types both identifiers blind and finds out at
the end.

The Storekeeper's version is `_schedule_lookup` / `_do_lookup` / `_apply_lookup` in
`storekeeper_app.py` (~1657-1730): a 400ms debounce on every keystroke, which fills the
sibling identifier and the type.

## Scope

- Debounced (400ms) resolution on both identifier fields, filling the sibling field and the
  asset type from the sheet, plus a visible not-found state before submit fails.
- Read the sheet **in process** - `_load_lookup_table()` is right here; do not make the GUI
  call `GET /lookup` over the network to ask itself a question.
- Nothing about rule 6 loosens: `_create_transaction` stays the enforcement point and still
  corrects and refuses on submit. This only shows the answer earlier.
- The dialog calls `ui_kit.fit` - keep it, and keep the buttons packed `side="bottom"`
  before the form.

## Cascade

- `CLAUDE.md` -> Server GUI -> the **Add Transaction** bullet.
- Run `python tools/server-checks.py`, which opens and measures this dialog.
