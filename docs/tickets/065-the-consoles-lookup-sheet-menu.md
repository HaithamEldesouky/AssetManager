# 065 - The console's Lookup Sheet menu: Proposals and Sync reached from one door

**Type:** feature · **Depends on:** nothing (lands before 060, which moves the windows this edits) · **Found by:** console review, Sep 2026 · **Issue:** [#240](https://github.com/HaithamEldesouky/AssetManager/issues/240)

## Finding

The Lookup Sheet and everything that feeds it are reached through a chain that starts
at a control about something else. `run_gui`'s action row (`ACTIONS`,
`server_gui.py:7170-7201`) carries **Database Location** as its sixth button, ungated;
that dialog (`change_db_location`, inside `run_gui`, `server_gui.py:6520-6642`) carries a
button **Assets in the Lookup Sheet** (`:6637`) that opens `manage_assets` (`:926`); and
that window's footer (`:1554-1574`) carries **Import Assets**, **Asset Sync** and
**Proposals**. The comment at `:7185-7197` records this as a deliberate port of the chip
#205 removed, so the chain would not be orphaned - not as a design.

Asset Proposals has **two** doors: that footer button (`:1569`) and an entry in the
Server Administration menu (`server_administration`, `server_gui.py:6284-6395`) with a
pending count (`proposals_label` / `open_proposals`, `:6376-6395`). Two doors onto one
window is what this ticket removes, and the glossary decides the menu's name: the list
is the **Lookup Sheet** (`CONTEXT.md:70-72`), and "asset register" is a wording it
warns off.

## Scope

1. A new gated hub on the action row, **Lookup Sheet**, in the slot Database Location
   holds today (066 moves Database Location into Server Administration). Same door as
   Server Administration: `_console_unlock` asked once, then every entry. Entries, in
   this order:
   - **Lookup Sheet** - opens `manage_assets(root)`.
   - **Asset Proposals** - opens `asset_proposals`, carrying the pending count exactly
     as `proposals_label` does today. `proposals_label` and `open_proposals` move here
     from `server_administration`.
   - **Asset Sync** - opens `asset_sync(root)`.
2. `server_administration` loses its Asset Proposals entry.
3. `manage_assets`' footer loses **Proposals** and **Asset Sync**. **Import Assets**
   stays - it is an act on the table in front of the Admin, not a window of its own.
4. `change_db_location` loses **Assets in the Lookup Sheet** (`:6637-6642`).

Until 066 lands the rail is seven wide for one commit (Database Location still on it).
`tools/server_checks/console.py:27-77` measures the row rather than asserting its
count, so that is measured, not broken.

## Not in this ticket

- Connected Clients on the rail, Database Location into Server Administration - 066.
- Any change inside `manage_assets`, `asset_proposals` or `asset_sync` beyond the footer.
- Moving windows to `gui_*.py` - 060.

## Cascade

- `tools/server_checks/lookup.py:596-618` asserts `proposals_label` and `open_proposals`
  are defined inside `server_administration`. Point it at the new hub, keep the
  assertion that the label is the count.
- `tools/server_checks/console.py:2757` walks every window from the rail; the hub is a
  second gated menu and gets the same walk Server Administration gets.
- `docs/reference/apps.md:87-89` (Database Location "is the only place the path is
  stated", the Lookup Sheet footer "also opens Asset Proposals" and "opens Asset Sync") -
  all three sentences stop being true; rewrite them around the hub.
- `tools/cascade-audit.py:1763` `_FIT_APPS` counts control-fit per app; no new file, so
  no change expected - confirm.
- `CONTEXT.md` glossary: no new term. The hub is called what the list is called.

## Verification

- `ast.parse()` on `server_gui.py`.
- `py -3.12 tools/gate.py` on the diff.
- By hand against a running server: open the hub, each of its three entries once;
  confirm Server Administration no longer lists Proposals, the Lookup Sheet footer no
  longer carries Proposals or Asset Sync, and Database Location has no Lookup button.
  The pending count on the hub entry changes when a proposal is filed.
