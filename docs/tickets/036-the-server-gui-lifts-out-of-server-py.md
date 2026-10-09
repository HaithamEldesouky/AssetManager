# 036 - The Server GUI lifts out of server.py

**Type:** refactor · **Depends on:** 035 · **Found by:** architecture review, Sep 2026 · **Issue:** [#207](https://github.com/HaithamEldesouky/AssetManager/issues/207)

## Finding

`server.py` is 18,703 lines. The Server GUI is 7,823 of them - 42% of the file - and it is
one concern with one entry point, `run_gui()`, called once on the last line of the file
(`server.py:18703`).

Nothing but that one call reaches into it. Verified:

- No function defined at or after 10257 has a caller below it, **except** the two
  certificate functions that 035 moves out first.
- `THEME` - `ui_kit.Theme(globals(), ...)` at `server.py:10281`, which binds 22 colour
  names into the module's globals - is referenced nowhere before 10257.
- The console door is console-only. `_console_unlock` (3198), `_capability_state` (3248),
  `_capability_holders` (3259) and `simple_password_prompt` (4430) are called from 14790,
  16096, 16968, 17793, 11971, 11972, 12793 and 15523. Every one is inside the GUI region.
  No route uses any of them.

So the GUI is already a module in everything but placement. What it lacks is a file.

**Why this and not a deepening ticket.** It deletes almost nothing - the lines move, they
do not go. What it buys is that `server.py` becomes ~10,361 lines of API and register, and
the console becomes a file you can open. The review that produced this ticket recommended
deepening first; the ask was file size first, and this is the honest version of that: a
move, not a redesign, with no behaviour change to argue about.

## Scope

One new file, `server_gui.py`.

1. **Move, verbatim:**
   - `server.py:10257-15545` - theme, helpers, `_ScrollArea`, `asset_proposals`,
     `asset_sync`, `manage_assets`, the unsaved-tracking block, `capability_passwords`,
     `manage_users`, `client_list`, `system_log`, `backup_restore`, `mail_settings`,
     `notification_rules`, `manage_records`.
   - `server.py:16065-18424` - `server_settings` and `run_gui`.
   - The console door: `_console_unlock`, `_capability_state`, `_capability_holders`,
     `simple_password_prompt`.

2. **The import goes one way.** `server_gui` imports `server`; `server` must not import
   `server_gui` at module level. The single call at `server.py:18703` becomes a deferred
   import inside the interactive-mode branch - which is also what keeps `server.py`
   importable in session 0 with no display, as `CODING_STANDARDS.md` "Headless safety"
   requires.

3. **`THEME` moves with the window.** `ui_kit.Theme(globals(), ...)` binds into whichever
   module calls it, so after the move it binds into `server_gui`'s globals, not
   `server.py`'s. Nothing before 10257 reads those names, so nothing breaks - but see the
   cascade, because a gate is asserting the old arrangement.

4. **`server.py` loses `import ui_kit`** at line 30, if nothing else in it uses ui_kit.
   Check before deleting; do not assume.

## Not in this ticket

- Any change to what a window does, how it is laid out, or what it measures.
- Deepening anything. No new interface, no Register, no auth module. Those are 038 and 039
  and they are deliberately behind this.
- Splitting `tools/server-checks.py`, which is 18,645 lines and has the same problem. File
  it separately if wanted; it ships in no package and hurts less.

## Cascade

- `CLAUDE.md` - "The files" table gains `server_gui.py`; the `server.py` row stops saying
  it holds the Tkinter console.
- `docs/reference/architecture.md` - the same, in full. **The `ui_kit.py` and `common.py`
  rows here are ~1,978 and ~1,931 characters on one line each** (`ticket-workflow.md`), so
  anything else touching them is sequenced against this.
- `docs/reference/apps.md` - the Server GUI section now names a different file.
- `docs/CODING_STANDARDS.md:12-22` "Where code goes".
- `tools/package.ps1:147` - `$SourceFiles` gains `server_gui.py`. **Same single line 035
  edits.** Sequenced, not parallel.
- `tools/cascade-audit.py:1647` - the check "`%s` restates none of the %d names its Theme
  binds" reads `server.py`. After the move the Theme binds into `server_gui.py`, so the
  check must follow or it silently asserts nothing - which is exactly the
  "passes by finding nothing" failure `CODING_STANDARDS.md` forbids.
- `tools/server-checks.py` - stages and imports `server.py`; its GUI groups now want
  `server_gui.py` staged beside it.
- `tools/dev-run.ps1` if it stages server sources by name.

## Verification

- `ast.parse()` both files.
- **Import `server.py` with no display and confirm it still imports.** This is the
  regression that matters; run it in a session with `DISPLAY` unset or under a service
  account.
- `py -3.12 tools/gate.py --all`, and read the Theme-binding check's output specifically -
  confirm it reports a non-zero count of names against `server_gui.py` rather than passing
  vacuously against `server.py`.
- Open every console window once, by hand: the door, Manage Users, Manage Assets, Asset
  Proposals, Asset Sync, Connected Clients, System Log, Backup/Restore, Mail Settings,
  Notification Rules, Manage Records, Capability Passwords, Server Settings.
- Run the server headless behind IIS and confirm `serve` mode is untouched.

## How it landed

Scope §2 said "`server_gui` imports `server`", which cannot happen: `applaunch.py`
runs `server.py` as `__main__` through `runpy.run_path`, so an `import server` inside
`server_gui.py` would start a **second** copy of the whole server rather than reach
the one already running - the exact wall #206 hit for `server_cert.py`. The fix is
the same shape `server_cert.bind()` uses, one level simpler: `server_gui.py` reaches
for dozens of server names across windows that were never written to take them as
arguments, so binding them one at a time the way `server_cert.bind()` does would be
a second copy of `server.py`'s own globals, drifting the moment one changed. Instead
`bind(server_module)` stores the **module object itself** as `S`, and every reference
inside the moved code to a name that stays in `server.py` is written `S.<name>`,
looked up on that live module at call time - so `tools/server-checks.py`'s
`M.ADMIN_CFG = {...}` and `M._gui_snapshot = spy` are seen exactly as before the move,
since `S` and `M` are the same object. `import server_gui` and the `bind()` call sit
at `server.py`'s module level, unconditional rather than deferred into the interactive
branch as §2 also proposed - `server_gui.py` has to import cleanly with no display
regardless, so nothing is gained by delaying it, and the entry point's bare
`run_gui()` call needs the name in scope either way.

`_since_ts`, `_gui_snapshot` and `_set_capability_password` sat inside the moved line
ranges but stayed in `server.py`: the first two because `tools/server-checks.py`
reads and monkeypatches `M._since_ts`/`M._gui_snapshot` directly, and a name a test
rebinds on the module has to be looked up on that module - a bare copy carried into
`server_gui.py` would leave the patch invisible to the window reading it. The third,
`_set_capability_password`, is called from nowhere but the moved `capability_passwords`
window, but `tools/server-checks.py` calls `M._set_capability_password(...)` directly
as an enforcement helper, the way it does `_create_transaction` and
`_modify_transaction`, so it stays server-side and the moved window reaches it as
`S._set_capability_password`. Fourteen names besides `run_gui` needed a flat
`from server_gui import (...)` back into `server.py` for the same reason - every one
`tools/server-checks.py` reaches by `M.<name>`: `THEME`, `_CONSOLE_UNLOCKED`,
`_CONSOLE_UNSAVED`, `_capability_state`, `_ago_ts`, `_client_colour`, `_console_close`,
`_console_unsaved`, `_status_of`, `_transaction_client`, `_transaction_log_rows`, and
the eleven console-window functions (`asset_proposals`, `asset_sync`, `backup_restore`,
`capability_passwords`, `client_list`, `mail_settings`, `manage_assets`,
`manage_records`, `manage_users`, `notification_rules`, `system_log`). `_CONSOLE_UNLOCKED`
and `_CONSOLE_UNSAVED` are mutable lists the tests item-assign into
(`M._CONSOLE_UNLOCKED[0] = True`, `del M._CONSOLE_UNSAVED[:]`) rather than rebind, so
the flat import sharing the same list object is enough - unlike `ADMIN_CFG` or
`_gui_snapshot`, nothing about them needed `S.` on the `server_gui.py` side.

`server_gui.py` was mapped by AST rather than by the ticket's line numbers, which had
drifted once #206 moved 519 lines out ahead of this one. The move is 7,689 lines
(`console door`: 81; `simple_password_prompt`: 17; the main block minus the two
carve-outs: 7,591), each `ast.Name` load of a stays-name rewritten to `S.<name>` from
AST node positions applied bottom-up, verified by re-walking the rewritten source
with `symtable` and confirming no moved function shadows a stays-name as a local.
`ui_kit` stayed imported in `server.py`: `_make_server_tray_icon`, which stays
server-side, still calls `ui_kit.HAS_PIL` and `ui_kit.app_icon`.
