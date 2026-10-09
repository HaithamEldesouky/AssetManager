# 005 - Server GUI: manage the asset lookup from the Database card

**Type:** enhancement · **Depends on:** nothing

## What is asked

The Database card should be clickable, offer the database path, and let an admin add,
update and delete assets.

## Where it stands today

The Database chip already opens **Database Location** (`server.py` ~6103), which validates
through `_validate_db_path`, saves through `_save_server_cfg` and never moves the file - so
the path half of this is done and is not to be re-done.

What is missing is editing the **assets**, which live in `asset_lookup.xlsx` rather than in
`assets.db` (the transactions in the database are already managed by Manage / Delete
Records, and rule 6 means an asset the sheet does not know cannot be transacted at all).
`_load_lookup_raw()` and `_save_lookup_raw(rows)` already exist at `server.py` ~4326/4355
and have **no callers** - this ticket is their consumer.

> Scope note: read "manage records on db (update, add, delete assets)" as the asset lookup.
> If transactions were meant, that is Manage / Delete Records and already exists.

## Scope

- A window reached from the Database Location dialog (or from the same chip) listing the
  lookup rows - asset number, serial number, type, model - with add, edit and delete.
- **Admin password**, checked directly rather than through `_authorise`: only the admin may
  change the sheet, which is what makes it the trusted source of truth (rule 2), and
  `POST /lookup/upload` already demands it.
- Write through `_save_lookup_raw` so the console and `POST /lookup/upload` cannot disagree
  about what the sheet is. Re-read after writing so `_load_lookup_table`'s view is current.
- A row needs at least one of asset number / serial number, matching rule 5's shape, and a
  type - the distinct types are what `GET /asset_types` serves (rule 2), so a typo here
  adds a type to every client's dropdown.
- Size with `ui_kit.fit`, buttons packed `side="bottom"` before the form.

## Cascade

- `CLAUDE.md` -> Server GUI -> the Database chip bullet, and rule 11 (which says the sheet
  is updated at runtime via `POST /lookup/upload`) now has a second door.
- Run `python tools/server-checks.py` and `python tools/cascade-audit.py`.
