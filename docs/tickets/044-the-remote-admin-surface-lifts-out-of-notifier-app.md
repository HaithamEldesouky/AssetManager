# 044 - The Remote Admin surface lifts out of notifier_app.py

**Type:** refactor · **Depends on:** 037 · **Found by:** architecture review, Sep 2026 · **Issue:** [#218](https://github.com/HaithamEldesouky/AssetManager/issues/218)

## Finding

`notifier_app.py` is 4,972 lines. `#208`'s comment thread (Remaining order, above #210)
already named this candidate move unfiled: "`notifier_remote.py` (Remote Admin surface,
~2,240 lines)". Verified against the current tree:

`server.py:7217`'s point-of-view - Remote Admin lets an engineer reach the console from
their own tray icon, capability-password gated (rule 8, ADR-0006, ADR-0015) - a contiguous
block, `notifier_app.py:1721-3957`, one concern with no caller outside it but the tray
menu:

- `REMOTE_PANELS = ("config", "history", "import", "users", "mail", ...)` and
  `REMOTE_PANEL_LABELS` - `notifier_app.py:1721`, `1723`.
- `probe_remote_admin(server_url, password)` - `notifier_app.py:1747`.
- `class RemoteAdminWindow` - `1846`.
- `class RemoteUsersPanel` - `2426`.
- `class RemoteMailPanel` - `2750`.
- `class RemoteClientsPanel` - `2954`.
- `class RemoteProposalsPanel` - `3261`.
- `class RemoteNotifyRulesWindow` - `3488`.
- `class RemoteCorrectionWindow` - `3660`.
- `class SettingsWindow` - `3775`.

The block ends at `3957`, immediately before `class NotifierApp` at `3958`. 3957 - 1721 +
1 = 2,237 lines - the "~2,240" the #208 comment estimated, confirmed rather than copied
forward.

## Scope

One new module, `notifier_remote.py`, beside `notifier_app.py`.

1. **Move `notifier_app.py:1721-3957` verbatim** - the nine names above, in full, no
   behaviour change, no window resized, no dialog reworded.
2. **The module reaches back through `bind()`**, the shape `server_cert.py` set and
   `server_gui.py` (#207) repeated: `applaunch.py` runs `notifier_app.py` as `__main__`
   through `runpy.run_path` (`docs/runbooks/source-mode.md`), so `import notifier_app`
   from inside `notifier_remote.py` would start a second tray client rather than reach the
   one running. `notifier_remote.bind(notifier_module)` stores the module object; every
   reference inside the moved code to a name that stays in `notifier_app.py` - `common`
   helpers it already imports directly are unaffected, but anything reached off
   `NotifierApp` itself, the config dict, or a module-level helper defined below 1721 -
   is rewritten `N.<name>`, looked up live. Grep `notifier_app.py` for what the moved block
   reaches below line 3957 before finishing this step; do not assume the list is empty
   because 036's wasn't.
3. **`notifier_app.py` imports `notifier_remote`** at module level (unconditional, the same
   choice 036's "How it landed" note explains for `server_gui`: the tray app has to import
   cleanly regardless, so nothing is gained by deferring it) and calls
   `notifier_remote.bind(sys.modules[__name__])` once, then reaches the moved names the
   tray menu needs (opening `RemoteAdminWindow`) as `notifier_remote.<name>`.

## Not in this ticket

- Any change to what a Remote panel does, its layout, or its wording. A move, not a
  redesign - the same rule 036 held to.
- 037 (#208)'s own scope, the Pending decision module below the popup widgets. This ticket
  depends on it only because both edit `notifier_app.py` and the same cascade lines named
  below; sequence behind 037, do not fold the two together.
- Splitting anything else out of `notifier_app.py`. What remains after this move is
  `class NotifierApp` and the popup/tray machinery 037 is already working on.

## Cascade

- `$Payload` in `tools/bundle-client.ps1:125` - currently
  `@("applaunch.py", "common.py", "ui_kit.py", "client_update.py")`. `notifier_remote.py`
  is not a shared module the way these four are - it ships only where `notifier_app.py`
  does - so check how the Notifier's own file is staged (`tools/bundle-client.ps1:226`)
  rather than assuming it belongs in `$Payload` itself; name which line actually changes.
- `SOURCE_FILES` in `installer.py:49` - the Notifier's entry gains `notifier_remote.py`.
- `tools/client-checks.py:78` `APPS = ("storekeeper_app.py", "notifier_app.py",
  "installer.py")` is unaffected by name (`notifier_remote.py` is not an app), but the
  staging block around `tools/client-checks.py:167-219` that copies each app beside its
  shared modules needs `notifier_remote.py` added wherever it stages `notifier_app.py` -
  check the exact line, do not guess it from `APPS`.
- `tools/gate.py` `MAP` (`tools/gate.py:78`) - `notifier_remote.py` falls under the
  existing `r"^(storekeeper_app|notifier_app|installer|applaunch|client_update)\.py$"`
  row only if added to it by name; add it, tagged `("client",)`.
- `tools/dev-run.ps1:283` `$ClientShared = @("common.py", "ui_kit.py",
  "client_update.py")` - `notifier_remote.py` is Notifier-only, not shared with the
  Storekeeper, so it does **not** join `$ClientShared`; instead the Notifier's own
  `New-AppDir` call (`tools/dev-run.ps1:294`) needs it added to its file list, same
  distinction as `client-checks.py` above.
- `CLAUDE.md` "The files" table - the `notifier_app.py` row's description changes to say
  what stays; a `notifier_remote.py` row is added.
- `docs/reference/architecture.md` and `docs/reference/apps.md` - the same, in full;
  `apps.md`'s Notifier section now names which file owns Remote Admin.
- `docs/CODING_STANDARDS.md` "Where code goes" - gains the module.
- `tools/cascade-audit.py:1347` `SHIPS` regex - lists `notifier_app\.py` but not a sibling
  module by name; **`notifier_remote.py` is not itself shipped as a package root, it ships
  inside the Notifier's payload**, so check whether `SHIPS` needs it added (if the audit
  walks the package's file list rather than only these top-level names) before assuming it
  does not.
- `tools/cascade-audit.py:1460` `BESIDE_MODULES` - reads module-level assignments out of
  `server.py`, `storekeeper_app.py`, `notifier_app.py`, `common.py`, `client_update.py`,
  `applaunch.py`, `installer.py`, `ui_kit.py`. `REMOTE_PANELS` and `REMOTE_PANEL_LABELS`
  move out of `notifier_app.py`; if any check in this file reads those two names off
  `notifier_app.py` specifically, point it at `notifier_remote.py` instead, or it passes by
  finding nothing (`CODING_STANDARDS.md`'s own name for that failure).
- `tools/cascade-audit.py:1546` `_FIT_APPS` - `[("Server GUI", "server_gui.py"),
  ("Storekeeper", "storekeeper_app.py"), ("Notifier", "notifier_app.py"),
  ("installer", "installer.py")]`. This counts control-fit by app, not by file that
  defines a window; check whether the Remote Admin windows' fit measurements are counted
  against `notifier_app.py` by name and, if the check walks the file rather than the
  running app, point the "Notifier" entry at both files or add a row.
- `tools/cascade-audit.py:1765` `_EVENT_SOURCES = ("server.py", "server_gui.py",
  "server_cert.py", "common.py", "storekeeper_app.py", "notifier_app.py")` - walks each
  file's AST for `_log_event`/event-name calls. If any Remote Admin panel logs a System Log
  event (check by grep before assuming none do), `notifier_remote.py` must join this
  tuple or its events stop being asserted, which is silent rather than loud.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `notifier_app.py` with no display and confirm it still imports** - the same
  regression 036 verified for `server_gui.py`, because `notifier_remote.py` is imported
  unconditionally.
- `py -3.12 tools\client-checks.py` green.
- Open the tray icon's Remote Admin window by hand against a running server: Users, Mail,
  Clients, Proposals, Notify Rules, the correction window, and Settings - every panel named
  in Scope §1, once each.

## How it landed

`notifier_remote.py`, 2,333 lines - 2,247 moved verbatim out of
`notifier_app.py:1713-3959` plus an 86-line header - and `notifier_app.py` down from
4,919 lines to 2,683. The ticket's line numbers were written against a tree before
#208 landed; the block is the same block, banner (`# --- Remote Admin (R2) ---`)
through `SettingsWindow`'s last line, and it is 2,247 rather than the 2,237 the ticket
computed because the banner and the blank lines around it came with it.

Built the way 036 was: every module-level name `notifier_app.py` binds was collected
with `symtable`, so "does this function resolve NAME as a global" was answered the way
Python's own scoping answers it rather than by a text search's guess, and each
reference was rewritten at its exact byte position, bottom-up. **Fifteen names** stay
in `notifier_app.py` and are read `N.<name>`, 24 references in all: `DEFAULT_CFG`,
`COMMAND_ASKS`, `THEME`, the three `*_RANGE` bounds and the three `validate_*` readers
that hold them, `save_config`, `fetch_members`, `_style_notifier`, `_tag_status`,
`_tag_clients` and `_status_of`. Nine names moved out and **two** of them are reached
from what stayed - `RemoteAdminWindow` and `SettingsWindow`, both off the tray menu,
now `notifier_remote.<name>`; nothing else in `notifier_app.py` looks into the block,
which is what made it a block. The imports the moved code also reads - `tk`, `ttk`,
`filedialog`, `os`, `base64`, `ui_kit`, and `api`, `log_event` and `offline_url_notice`
out of `common` - are imported by the new module itself rather than reached through
`N`, which is what Scope §2 means by "`common` helpers it already imports directly are
unaffected".

**The palette is the one thing not reached through `N`.** The moved code reads `BG`,
`TEXT`, `CARD2` and their kin 302 times and calls `font(...)` 90 more, and those names
are written down nowhere in `notifier_app.py`: `ui_kit.Theme` puts them into **an app's
module globals** at runtime out of `ui_kit.DARK`, which is the whole reason a widget
construction can say `bg=BG` at all. So `N.BG` would have been reaching through one
module's namespace for a value that belongs to neither, in 392 places, and would have
made the move visibly not-verbatim in exactly the lines the ticket asked to leave
alone. `bind()` seeds this module's globals from `THEME.palette()` and hands that same
seeding to `THEME.watch()` - the hook the Theme already runs after every swap, and the
one a `ui_kit.Surface` registers its own redraw on - so an open Remote Admin window is
repainted by a theme change and one opened afterwards is born in the current palette,
both exactly as before. No change to `ui_kit.py`; `font` is a plain
`from ui_kit import font`, a face not being a palette and never moving on a swap.

Both files stay CRLF, counted before and after every write, and `tools/*.ps1` stay pure
ASCII, asserted on the bytes rather than assumed.

**Cascaded:** `installer.py`'s `SOURCE_FILES["notifier"]`; `tools/bundle-client.ps1`,
where the line that changed is `$Apps.notifier.Extra` (line 116) and **not** `$Payload`
- a Notifier-only module in the shared list would have the Storekeeper's zip carrying
and installing a file it never imports, which is the distinction #208 drew and this
follows; `tools/dev-run.ps1`, the same distinction, where the Notifier's `New-AppDir`
call takes a new `$NotifierOwn` list rather than `$ClientShared` growing;
`tools/gate.py`'s client row; `tools/client-checks.py`, which stages the module, loads
it as `NR` *before* `notifier_app.py` so the app's own import finds the staged copy,
closes its `api` door too - a fourth copy of that name - and reads the 21 moved-name
references off `NR` instead of `NT` (`NT` and `NR` being the same width, nothing
re-aligned); `tools/cascade-audit.py`'s `SHIPS` regex, which does need the name because
it answers "did a change invalidate a built package" and this file rides inside the
Notifier's payload, and its `_EVENT_SOURCES`, which does need it because the Host & Port
panel logs `settings.url_changed` and an event nothing reads is asserted against nothing
- silently; `_FIT_APPS` in the same file, which now counts **files per app** rather than
a file per app, six of the Notifier's eleven `ui_kit.fit` callers having moved while the
sentence in `docs/reference/architecture.md` that count is held against still says
eleven, correctly, because a window is the Notifier's wherever the class is written
down; `CLAUDE.md`'s file table; `docs/reference/architecture.md`,
`docs/reference/apps.md` and `docs/CODING_STANDARDS.md` ("Where code goes").

**Checked and deliberately not cascaded:** `cascade-audit.py`'s `BESIDE_MODULES` - it
reads module-level `os.path.join(BASE, ...)` assignments to hold what an app writes
beside itself against `.gitignore`, the moved block has none, and `notifier_pending.py`
is absent from that tuple for the same reason. Nothing in that file, or anywhere else in
the repo, reads `REMOTE_PANELS` or `REMOTE_PANEL_LABELS` off `notifier_app.py`; the only
reader of either is `tools/client-checks.py`, which now reads them off `NR`.
`tools/client-checks.py`'s `APPS` is unchanged - `notifier_remote.py` is not an app and
has no entry point. No `APP_VERSION` bump: a refactor with no behaviour change, and the
release that ships it stamps it. No new System Log event, no endpoint, no database
column, no new file written beside an app.
