# 045 - The Storekeeper's export lifts out

**Type:** refactor · **Depends on:** 044 (cascade lines only) · **Found by:** architecture review, Sep 2026 · **Issue:** [#219](https://github.com/HaithamEldesouky/AssetManager/issues/219)

## Finding

`storekeeper_app.py` is 4,160 lines. #208's comment thread named this candidate alongside
`notifier_remote.py`: "`storekeeper_export.py` (~415)". Verified against the current tree:

- `class ExportDialog` - `storekeeper_app.py:185`.
- `def _write_excel(data, path, from_dt=None, to_dt=None)` - `storekeeper_app.py:354`.

The block ends at `600`, immediately before `class StorekeeperApp` at `601`. 600 - 185 +
1 = 416 lines - the "~415" the #208 comment estimated. One concern: `ExportDialog` is the
window that picks a date range, `_write_excel` is what it calls to write the workbook, and
nothing else in `storekeeper_app.py` calls either.

## Scope

One new module, `storekeeper_export.py`, beside `storekeeper_app.py`.

1. **Move `storekeeper_app.py:185-600` verbatim.**
2. **The module reaches back through `bind()`**, same shape as 044: `applaunch.py` runs
   `storekeeper_app.py` as `__main__`, so `import storekeeper_app` from inside
   `storekeeper_export.py` starts a second Storekeeper client. Grep what the moved block
   reaches below line 600 before writing `bind()`'s signature - do not assume it needs
   nothing, the way 036's "How it landed" note found fourteen names 035's plan missed.
3. **`storekeeper_app.py` imports `storekeeper_export`** at module level and calls
   `storekeeper_export.bind(sys.modules[__name__])` once, then opens `ExportDialog` as
   `storekeeper_export.ExportDialog`.

## Not in this ticket

- Any change to the export's columns, date filtering, or the workbook's formatting. A
  move, not a redesign.
- `notifier_remote.py` (044) or anything else in the Notifier.

## Cascade

Same set 044 owes, because both are a client module lifting out of its app and both cross
the same lines - this is why 045 depends on 044: not because the code is related (it is
not; Storekeeper and Notifier share no state), but because both cascades land in
`tools/bundle-client.ps1`, `installer.py`'s `SOURCE_FILES`, `tools/client-checks.py`'s
staging block, `tools/gate.py`'s `MAP`, `tools/dev-run.ps1`, `CLAUDE.md`'s files table,
`docs/reference/architecture.md` and `docs/reference/apps.md`, and
`docs/CODING_STANDARDS.md` "Where code goes" - the exact trap `ticket-workflow.md` "Two
tickets that cascade to the same line" describes, and the reason 035/036 were sequenced
over one line in `package.ps1`. Land 044 first; re-read its Cascade section against the
tree as it stands once 044 has merged, rather than copying its line numbers forward -
they will have moved.

Specific to this ticket:

- `SOURCE_FILES` in `installer.py:49` - the Storekeeper's entry gains
  `storekeeper_export.py`.
- `tools/client-checks.py`'s staging block, wherever `storekeeper_app.py` is staged beside
  its shared modules (adjacent to the line 044 touches for `notifier_app.py` - re-find it
  once 044 has landed).
- `tools/dev-run.ps1:285` `New-AppDir "storekeeper" (@("storekeeper_app.py") +
  $ClientShared)` - `storekeeper_export.py` is Storekeeper-only, so it joins the app's own
  list, not `$ClientShared`, the same distinction 044 draws for `notifier_remote.py`.
- `tools/gate.py` `MAP` - `storekeeper_export.py` added to the client-app row, tagged
  `("client",)`.
- `tools/cascade-audit.py:1347` `SHIPS`, `:1460` `BESIDE_MODULES`, `:1546` `_FIT_APPS`,
  `:1765` `_EVENT_SOURCES` - check each against `storekeeper_export.py` the way 044 checks
  them against `notifier_remote.py`: does `ExportDialog` log a System Log event (grep
  before assuming), is anything module-level in the moved block read by name, is its
  control-fit counted under "Storekeeper" by file. Name what each check does and does not
  need, rather than copying 044's four bullets as given - `storekeeper_export.py` has no
  `REMOTE_PANELS`-shaped constant to relocate, so `BESIDE_MODULES` most likely needs
  nothing here; confirm rather than assume.
- `CLAUDE.md`, `docs/reference/architecture.md`, `docs/reference/apps.md`,
  `docs/CODING_STANDARDS.md` "Where code goes" - each gains the module the same way 044's
  does.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- **Import `storekeeper_app.py` with no display and confirm it still imports.**
- `py -3.12 tools\client-checks.py` green.
- Open Export from the Storekeeper's window by hand, pick a date range, and confirm the
  workbook still writes.

## How it landed

`storekeeper_app.py:183-596` - the banner through `_write_excel`'s last line, 414 lines -
is `storekeeper_export.py`, which is 503 with its own header and imports.
`storekeeper_app.py` drops from 4,160 lines to 3,754. The Finding names 185-600; it is
the same block, and 414 rather than 416 because the banner came with it and the blank
lines either side stayed behind.

**What it reaches back for is the palette, and nothing else.** Built with a `symtable`
sweep rather than by hand, the way 036's note said 035's plan should have been: every
top-level name `storekeeper_app.py` binds was collected, and "does this block resolve
NAME as a global" was answered the way Python's own scoping answers it. Nine names came
back - `tk`, `ttk`, `messagebox`, `filedialog`, `datetime`, `date`, `api`,
`TEAM_MEMBERS`, `ui_kit` - and every one of them is an **import** rather than state, so
this module imports them itself. `S.<name>` for those would be borrowing one module's
import list rather than reading a value that belongs to it, which is the opposite of
what #218's fifteen `N.<name>` references are. So `bind()` is here for one reason:
`ui_kit.Theme` binds the colours into an app's module *globals*, they are written down
nowhere in `storekeeper_app.py`, and `S.BG` would reach through one namespace for a
value belonging to neither - `bind()` seeds this module's globals from
`S.THEME.palette()` and hands that same seeding to `S.THEME.watch()`. `SUCCESS_HOT`,
one of this app's own three extras, arrives that way too, the palette being the merged
table rather than `ui_kit.DARK`. Proved rather than asserted: importing both modules
with no Tk root and driving `THEME.set('light')`/`('dark')` shows
`storekeeper_export.BG` following `storekeeper_app.BG` in both directions, and a second
`symtable` sweep over the finished file leaves no free global unresolved. `font` is a
plain `from ui_kit import font`, a face not being a palette. The call site is
`storekeeper_export.ExportDialog(...)` in `_open_export`; nothing else in
`storekeeper_app.py` looked into the block, which is what made it a block. Both files
stay CRLF, counted before and after every write, and `tools/*.ps1` stay pure ASCII,
asserted on the bytes.

**Cascaded:** `installer.py`'s `SOURCE_FILES["storekeeper"]`; `tools/bundle-client.ps1`,
where the line that changed is `$Apps.storekeeper.Extra` and **not** `$Payload`, the
distinction #208 drew and #218 followed - the Notifier's zip would otherwise carry and
install a file it never imports; `tools/dev-run.ps1`, the same distinction, where the
Storekeeper's `New-AppDir` call takes a new `$StorekeeperOwn` list beside #218's
`$NotifierOwn` rather than `$ClientShared` growing; `tools/gate.py`'s client row;
`tools/client-checks.py`, which stages the module, loads it as `SE` *before*
`storekeeper_app.py` so the app's own import finds the staged copy, closes its `api`
door - a fifth copy of that name - moves the export group's `_write_excel` call and its
`messagebox` stub onto `SE`, reads the group's three source assertions out of the two
files as one mapping, and adds `storekeeper_export.py` to `SRC_FILES` and to the
`raise_open`/`single` pair, the split running straight through that pair exactly as
#218's did: `_open_export` kept the `raise_open` and `ExportDialog` took the `single`
with it. `tools/cascade-audit.py`'s `SHIPS` regex, because this file rides inside the
Storekeeper's payload and a change to it does invalidate that zip; and `_FIT_APPS`,
where the Storekeeper becomes two files - one of its nine `ui_kit.fit` callers moved,
while the sentence in `docs/reference/architecture.md` that count is held against still
says nine, correctly, a window being the Storekeeper's wherever the class that draws it
is written down. `CLAUDE.md`'s file table; `docs/reference/architecture.md`,
`docs/reference/apps.md` and `docs/CODING_STANDARDS.md` ("Where code goes").

**Checked and deliberately not cascaded:** `cascade-audit.py`'s `BESIDE_MODULES` - it
reads module-level `os.path.join` assignments to hold what an app writes beside itself
against `.gitignore`, and the moved block has none, which is also why
`notifier_pending.py` and `notifier_remote.py` are absent from that tuple.
`_EVENT_SOURCES` - the moved block calls `log_event` nowhere, so unlike #218's Host &
Port panel it emits no System Log event; grepped rather than assumed. The typeface sweep
beside them, which exempts constants inside an openpyxl `Font(...)` call and would have
nothing to say about this file: every `"Segoe UI"` in `_write_excel` is inside one, and
an Excel workbook is not this product's window. `tools/client-checks.py`'s `APPS` is
unchanged - `storekeeper_export.py` is not an app and has no entry point. No
`APP_VERSION` bump: a refactor with no behaviour change, and the release that ships it
stamps it. No new endpoint, no database column, no new file written beside an app.

**Gates:** `py -3.12 tools/gate.py` is GREEN - cascade, client and deploy.
`client-checks.py` on its own is 69 groups, 927 assertions, 0 skipped. The by-hand step
was driven rather than clicked: a real Tk `ExportDialog` built out of the new module
against a stubbed `/export`, its date range read off the two fields it was born with,
and the workbook it wrote opened again - both sheets, the Detail columns in order, and
the Summary's Total agreeing with the rows. What was **not** done is the same click
against a live server on the Storekeeper's own machine.
