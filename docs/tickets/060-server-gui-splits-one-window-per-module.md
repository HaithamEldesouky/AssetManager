# 060 - server_gui.py splits one window per module

**Type:** refactor · **Depends on:** nothing (sequence after the 2.6.0 release) · **Found by:** modularisation review, Sep 2026 · **Issue:** [#235](https://github.com/HaithamEldesouky/AssetManager/issues/235)

## Finding

`server_gui.py` is 7,753 lines, 53 top-level nodes (`def`/`class` at module scope). Thirteen
of those are the console's windows, verified by grep
(`grep -nE '^def (asset_proposals|asset_sync|manage_assets|capability_passwords|manage_users|client_list|system_log|backup_restore|mail_settings|notification_rules|manage_records|server_settings|run_gui)' server_gui.py`),
with each span taken to the line before the next top-level `def`/`class`:

| Window | Lines | Span |
|---|---|---|
| `asset_proposals` | 378-652 | 275 |
| `asset_sync` | 653-925 | 273 |
| `manage_assets` | 926-1605 | 680 |
| `capability_passwords` | 1726-2013 | 288 |
| `manage_users` | 2014-2929 | 916 |
| `client_list` | 2930-3490 | 561 |
| `system_log` | 3491-3949 | 459 |
| `backup_restore` | 3950-4083 | 134 |
| `mail_settings` | 4084-4330 | 247 |
| `notification_rules` | 4331-4565 | 235 |
| `manage_records` | 4619-5395 | 777 |
| `server_settings` | 5396-6061 | 666 |
| `run_gui` | 6062-7753 | 1692 (to end of file) |

Between `manage_assets` and `capability_passwords` sits `class _Unsaved` (1606) and three
helpers (`_console_unsaved`, `_track_unsaved`, `_console_close`, 1616-1725) - the console's
dirty-tracking machinery, shared by every window below it, and not itself a window.
Between `notification_rules` and `manage_records` sit two small helpers,
`_transaction_log_rows`/`_transaction_client` (4566-4618), read only by `manage_records`.
`run_gui` (6062-7753) is the console's own root window, menu and dispatch - not one of the
twelve asset/admin windows, but the thing that opens all of them, and stays last.

**`S` is how every window reaches the running server.** `server_gui.py:42` declares
`S = None`; `bind(server_module)` (`server_gui.py:45-56`) sets it once, called from
`server.py:5498-5499` (`import server_gui; server_gui.bind(sys.modules[__name__])`) - not
line 8172, which this ticket's own filing guessed before the tree was measured against.
`applaunch.py` runs `server.py` as `__main__` through `runpy.run_path`
(`docs/runbooks/source-mode.md`), so nothing here may `import server` - the same
constraint `server_cert.py` and `server_gui.py` itself already answer with `bind()`.

**`THEME` and 22 colour names bind into `server_gui.py`'s own globals**, not a dict a
window could pass around: `ui_kit.Theme(globals(), _EXTRA_DARK, _EXTRA_LIGHT, ...)`
(`server_gui.py:187-188`) writes `ui_kit.DARK`'s 18 keys (`BG`, `CARD`, `CARD2`, `LINE`,
`ACCENT`, `ACCENT2`, `TEXT`, `SUBTEXT`, `SUCCESS`, `WARNING`, `DANGER`, `INPUT_BG`, `MONO`,
`FAINT`, `GROUND`, `GROUND2`, `GLASS`, `EDGE`) merged with this file's own four
(`SUCCESS_BG`, `SUCCESS_HOT`, `DANGER_BG`, `DANGER_HOT`, `server_gui.py:170-176`) into
`globals()` at import time, and rewrites them on every theme swap. A window moved out of
`server_gui.py` that still says `bg=BG` needs that name live in its own module, not
`server_gui.BG` read once at import and never updated.

`storekeeper_export.py` and `notifier_remote.py` already solved this for the clients, and
neither calls `ui_kit.Theme` a second time: each keeps its own `_bind_palette()`
(`storekeeper_export.py:73-83`, `notifier_remote.py:68-78`) that copies
`<app_module>.THEME.palette()` into its own `globals()` once at `bind()` and re-copies it
on `THEME.watch(_bind_palette)` - written through `globals()` rather than restated as
literals so `ui_kit.retint`'s widget-colour lookup still finds the name (the same reason
`ui_kit.DARK` exists at all). `tools/cascade-audit.py:1846-1863` already asserts no app
restates a Theme-bound name at module level; it walks `server_gui.py`,
`storekeeper_app.py` and `notifier_app.py` today and needs the new modules added or it
passes by finding nothing.

## Scope

One module per window, or per pair of small windows, beside `server_gui.py`, named
`gui_<window>.py`:

1. **`gui_proposals.py`** - `asset_proposals`, `asset_sync` (548 lines together; both work
   the Storekeeper's proposal queue against the same lookup, the natural pairing).
2. **`gui_assets.py`** - `manage_assets` (680 lines, on its own: the Database card's asset
   table is the largest single window here bar `manage_records` and `run_gui`).
3. **`gui_users.py`** - `capability_passwords`, `manage_users` (1,204 lines together; both
   are RBAC surfaces over the same permission table, rule 8).
4. **`gui_clients.py`** - `client_list` (561 lines).
5. **`gui_log.py`** - `system_log` (459 lines).
6. **`gui_backup.py`** - `backup_restore` (134 lines, the smallest - pair it with
   `mail_settings` if a reviewer prefers fewer files; state the choice made, either way).
7. **`gui_mail.py`** - `mail_settings`, `notification_rules` (482 lines together; the
   second reads mail's own recipient list).
8. **`gui_records.py`** - `manage_records` (777 lines, plus the two `_transaction_*`
   helpers it alone reads).
9. **`gui_settings.py`** - `server_settings` (666 lines).

`run_gui` and the console's own dirty-tracking machinery (`_console_unlock`,
`_capability_state`, `_capability_holders`, `simple_password_prompt`, `_tag_ages`,
`_hover`, `_ident`, `_status_of`, `_ago_ts`, `_when_ts`, `_ago`, `_when`,
`_client_colour`, `class _ScrollArea`, `_style_server_gui`, `class _Unsaved`,
`_console_unsaved`, `_track_unsaved`, `_console_close`, `bind`) stay in `server_gui.py`,
which becomes the console's shell: it imports the nine new modules and calls their window
functions from the menu, the same way it calls them today.

**Each new module reaches the server through `S` by importing it from `server_gui` after
`bind()`, not by calling `bind()` itself.** `server_gui.bind()` is called once, from
`server.py`, before any window opens; a second `bind()` per module would be a second door
onto the same server module for no reason `server_cert.py`'s or `#218`/`#219`'s shape
needs - those modules get their own `bind()` because their *app* (`notifier_app.py`,
`storekeeper_app.py`) is a `runpy` entry point that cannot be imported back, but
`server_gui.py` is not an entry point either (`server.py` is), so `gui_assets.py` saying
`from server_gui import S` after `server_gui.bind()` has already run reaches the same
module object with no import cycle: `server_gui.py` imports `gui_assets` (for its window
function) and `gui_assets.py` imports `server_gui` (for `S`), and neither import needs the
other finished first, since `S` is read at call time, inside a function, not at module
scope. State whichever seam is actually built if grepping the finished import graph shows
a cycle this reasoning missed.

**`THEME` stays in `server_gui.py`.** Every new module gets `_bind_palette()` copied from
`storekeeper_export.py`'s/`notifier_remote.py`'s shape: `from server_gui import THEME` (or
reached the same way as `S`), then its own `_bind_palette()` seeded once at import and
re-seeded on `server_gui.THEME.watch(_bind_palette)`. `font` stays a plain
`from ui_kit import font` in each new module, the same as the two client precedents, since
a face never moves on a theme swap.

## Not in this ticket

- Any layout or behaviour change to a window. A move, not a redesign.
- The console door (`_console_unlock`, `_CONSOLE_UNLOCKED`) or `run_gui`'s menu wiring -
  both stay in `server_gui.py`.
- Splitting `run_gui` itself, or the dirty-tracking helpers, into their own module. What is
  in scope is the twelve windows named above; the shell that opens them is not.

## Cascade

- `tools/package.ps1:152` `$SourceFiles` - gains the nine `gui_*.py` modules on the server
  entry (already carries `server.py`, `server_gui.py`, `server_cert.py`, the three
  registers, `server_mail.py`, `server_sync.py`, `server_clients.py`, `server_log.py`,
  `server_archive.py`, `server_lookup.py`, `ui_kit.py`, `ui_glass.py`, `run_server.py`,
  `applaunch.py`).
- `tools/dev-run.ps1:206` (`New-AppDir "server" @(...)`) - the same list, same nine
  modules added.
- `tools/server_checks/stage.py:211` and `:680` (the two `for _name in (...)` staging
  loops that copy `server.py`, `server_gui.py`, `server_cert.py`, ... into `STAGE`) - both
  need the nine new modules added, or a staged import of one fails.
- `tools/gate.py:87` `MAP` - the existing `(r"^server_gui\.py$", ("server",))` row either
  grows a pattern for the nine new names or gains nine rows; name which, and add it, or an
  edit to a `gui_*.py` module runs no gate.
- `tools/cascade-audit.py:1557` `SHIPS` (built from `_SHIPPED`, itself derived from the
  release scripts' own file lists) - gate-held per `CLAUDE.md`'s "a new module beside an
  app" row, so it should need no manual edit once `$SourceFiles` above moves; confirm this
  against the tree rather than trusting it here.
- `tools/cascade-audit.py:1763` `_FIT_APPS` - `[("Server GUI", ("server_gui.py",)), ...]`
  counts control-fit by file per app, the same shape `#218`'s `_FIT_APPS` entry took for
  the Notifier; add the nine `gui_*.py` names to the `"Server GUI"` tuple.
- `tools/cascade-audit.py:1846-1863` (the Theme-restatement walk over `server_gui.py`,
  `storekeeper_app.py`, `notifier_app.py`) - add each new module that gets its own
  `_bind_palette()`, or the check passes by never looking at it.
- `tools/cascade-audit.py:1983` `_EVENT_SOURCES` - grep each new module for `_log_event`
  calls before assuming none moved; add whichever do, or a System Log event stops being
  asserted, silently.
- `CLAUDE.md` "The files" table - the `server.py` row's description is unaffected (it
  already says "Tkinter console" as one of the three modes, not that the console lives in
  one file); no new row is warranted here since these are the console's own internals, not
  a file the table lists as a component - confirm this reading against how `#207`'s and
  `#218`'s tickets treated their own new files before deciding, and add rows if the
  table's convention is "every file", not "every component".
- `docs/reference/architecture.md` - the Server GUI section's file list gains the nine
  modules, and the paragraph on how `server_gui.py` reaches `server.py` through `bind()`
  gets a second paragraph on how the nine windows reach `server_gui.py` in turn.
- `docs/reference/apps.md` - the Server GUI section names which module owns which window,
  the same way `apps.md`'s Notifier section names `notifier_remote.py` for Remote Admin
  since `#218`.

## Verification

- `ast.parse()` every file touched or added.
- Headless import of `server.py` (`py -3.12 -c "import server"` with no display, or
  whatever the existing headless-import check does) - the same regression `#207`'s ticket
  verified for `server_gui.py` itself, now with nine more modules imported unconditionally
  underneath it.
- `py -3.12 tools/gate.py --all`.
- Open every window once by hand against a running server: Asset Proposals, Asset Sync,
  Manage Assets, Capability Passwords, Manage Users, Connected Clients, System Log, Backup
  & Restore, Mail Settings, Notification Rules, Manage Records, Server Settings, and the
  console's own root window (`run_gui`) - thirteen opens, one per row in the Finding table
  above.
