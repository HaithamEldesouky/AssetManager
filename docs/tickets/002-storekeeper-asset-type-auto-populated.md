# 002 - Storekeeper: Asset Type is auto-populated from the lookup sheet, not picked

**Type:** enhancement · **Depends on:** nothing

## What is asked

In the Storekeeper form the Asset Type should be **auto-populated** from the lookup sheet
rather than selected by the user.

## Where it stands today

`storekeeper_app.py` ~line 904: `self.v_type` is a `readonly` `ttk.Combobox` seeded from
`GET /asset_types`, defaulting to `"Laptop"`. `_apply_lookup` (~1681) sets it from the
matched row and sets `self._lookup_locked = True`; `_clear_lookup_lock` (~1727) unlocks it.
So today it is a dropdown that happens to be filled in and locked when a lookup matched,
and a free choice otherwise.

## Scope

- Replace the combobox with a read-only display of what the lookup sheet gave, with an
  explicit empty state (`-`) before any identifier has matched.
- `_submit` (~1514) reads `self.v_type.get()`. Keep the submitted shape identical: the
  server corrects the type from the sheet anyway (rule 6), and an asset the sheet does not
  know is refused with `not_in_lookup` whatever type was sent.
- `_lookup_locked` / `_clear_lookup_lock` collapse into "what the sheet said" - there is no
  lock left to hold.
- The **history filter** at ~line 993 (`filt("Type", ["All"] + self.asset_types, ...)`)
  stays a real dropdown: it filters, it does not describe an asset. `_load_asset_types`
  stays for it.
- Bulk Scan already takes the type from the lookup response (~1899) - leave it alone.

## Cascade

- `CLAUDE.md` -> Storekeeper App -> the **Form** and **Lookup auto-fill** bullets.
- Rule 2 in `CLAUDE.md` says "Clients load this list at startup (Storekeeper form + history
  filter)" - the form half stops being true.
- Run `python tools/client-checks.py`, which measures this window.
