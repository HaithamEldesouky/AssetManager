# Coding standards — Asset Manager

What the code in this repo already does. No linter or formatter is configured. The four
apps ship as source rather than compiled (rule 12), and each is a program spread over
several modules at the repo root rather than one file - the Asset Server alone is twelve
of them. So the rules below are about keeping one app's habits out of another's, and, since
035-048 took those modules out, about where a module belongs and how it reaches the
program that owns it.

Vocabulary comes from [CONTEXT.md](../CONTEXT.md); the rules and the cascade table
are in [CLAUDE.md](../CLAUDE.md), which routes to the reference documents under
[reference/](reference/architecture.md). Decisions already settled live in `docs/adr/` — read them
before re-litigating one.

## Where code goes

**One module per concern, and the concern is what a reader would name.** A module here is
a deep one: a small interface with most of the behaviour behind it, so a caller writes
`_create_transaction(...)` rather than the steps inside it. A block is lifted out when it
is one concern with one entry point that the rest of the file does not reach into - which
is what every move in 035-048 was, and why none of them edited a call site. It is not
lifted for length: `server.py` is still the largest file here and is not a candidate on
that ground alone.

**No second copy of a shared answer** (rule 10), and nothing added for a requirement that
does not exist yet - no abstraction, config knob or layer today's ticket does not ask for.
A module one app needs is that app's second module rather than `common.py`'s: the
Storekeeper has no pending queue and the Notifier has no store to export.

**A module reaches back to the program that owns it through `bind()`, never by importing
it.** `applaunch.py` runs each app as `__main__` through `runpy.run_path`, so an
`import server` - or `import notifier_app`, or `import storekeeper_app` - from a helper
module executes a second copy of the whole program instead of reaching the one already
running. `server_cert.py` set the pattern and every later module repeated it: the owning
program calls `<module>.bind(...)` at import and hands over the names the moved code
reads. There are two shapes of it and the choice is how many names there are - a keyword
list where they can be counted (`server_cert.py`, the three registers, and the six
modules 050-055 added), and the live module itself where they cannot,
`bind(sys.modules[__name__])` read back as `S.<name>` in `server_gui.py`, `N.<name>` in
`notifier_remote.py`, and the same call in `storekeeper_export.py` reaching for the
palette alone. Two kinds of name do not travel that way. A **sentinel** compared
by identity is imported rather than bound (`_KEEP`, from `register_engineers`), because a
default argument is evaluated at import and one bound afterwards would leave those
defaults holding a different object than callers compare against. A value the owner
**re-points while running** is handed over as a **callable** rather than as itself
(`db_path`), because a copy taken at `bind()` is the value as it was then.

**What a new module owes.** Four lists name the modules of this repo, nothing derives
them and no gate holds them, so a new module is added to each by hand: `MAP` in
`tools/gate.py`, the two staging lists in `tools/server_checks/stage.py`, and the staging
block in `tools/client_checks/stage.py` with the `SRC_FILES` tuple beside it. The lists that
used to belong on this paragraph are gate-held now and are not the reader's job -
`$SourceFiles` in `tools/package.ps1`, `tools/dev-run.ps1`'s staged lists, and `$Payload`
in `tools/bundle-client.ps1` against `SOURCE_FILES` in `installer.py`, each of which
`cascade-audit.py` will name a missing module in. Of the four that are left, `SRC_FILES`
is the one that costs coverage rather than a run: it is the list of files read as *text*,
so a module missing from it is never swept and the suite goes on passing about less and
less.

The modules, and what each one is. `tools/server-checks.py`, here and below, names the
server suite by the front door `gate.py` runs; the checks themselves have lived in
`tools/server_checks/`, one module per group, since 047. `tools/client-checks.py` names
the client suite the same way, its checks having lived in `tools/client_checks/` since
#238.

- `server.py` — the Flask API, the SQLite database, the background jobs, and the
  service/serve/GUI mode switch. One program, three modes: the app exes were retired
  at #061 and what Windows starts is a launcher (rule 12, rule 14).
- `server_gui.py` — the Tkinter console interactive mode opens, lifted out of
  `server.py` verbatim by #207. `server.py` imports it at module level and calls
  `server_gui.bind(sys.modules[__name__])`; every name the moved code reads that
  stays in `server.py` is written `S.<name>`, looked up on that live module rather
  than passed in one at a time the way `server_cert.py`'s `bind()` does - this
  module reaches for too many server names for a parameter list to be the honest
  shape of that.
- `gui_proposals.py`, `gui_assets.py`, `gui_users.py`, `gui_clients.py`,
  `gui_log.py`, `gui_backup.py`, `gui_mail.py`, `gui_records.py`,
  `gui_settings.py` — the console's twelve windows (#235), one module per
  window or per pair of windows over the same table. **These are the one set
  of modules here that do not call `bind()`**, and the reason is that their
  owner is not an entry point: `server.py` is, and it has already called
  `server_gui.bind()` before any window opens, so a `bind()` of their own
  would be a second door onto the same server module. Each writes
  `from server_gui import S` as the first line of the window instead, at call
  time, `S` still being `None` when `server_gui.py` imports them. The palette
  does not travel that way either — `ui_kit.Theme` binds it into
  `server_gui.py`'s globals, so each keeps a `_bind_palette()` of its own
  seeded at import and registered with `server_gui.THEME.watch`, which is
  `notifier_remote.py`'s and `storekeeper_export.py`'s shape. `server_gui.py`
  imports them below its `THEME` and re-exports the twelve window names, so
  `run_gui`, `server.py` and `tools/server-checks.py` call them as they did
  before the split.
- `server_cert.py` — the certificate lifecycle of ADR-0020, imported by `server.py`
  and called from both its routes and `server_gui.py`'s console. It resolves no path
  of its own: `server.py` hands it the four certificate paths and the helpers it
  calls, through `bind()` at import.
- `register_assets.py` — the Assets register (#215): the four functions that read
  and write the `assets` table, called from `server.py`'s lookup routes, from
  `server_gui.py`'s three asset windows as `S.<name>`, and directly by
  `tools/server-checks.py`. It opens no connection of its own - `server.py`
  hands it `get_db` and `_log_event` through `bind()` at import, the way
  `server_cert.py` takes its paths.
- `register_transactions.py` — the Transactions register (#216): the four
  functions that read and write the `transactions` table, called from
  `server.py`'s eleven transaction routes, from `server_gui.py`'s Manage
  Records as `S.<name>`, and directly by `tools/server-checks.py`. It takes
  `get_db` and twelve more names through `bind()` the same way, and it imports
  `register_assets` for `_asset_key_sql` — which asset a Transaction is about
  is the other register's rule, asked for rather than worded twice.
- `register_engineers.py` — the Engineers register (#217): the six
  functions that read and write the `team_members` table, called from
  `server.py`'s member routes, from `server_gui.py`'s Manage Users as
  `S.<name>`, and directly by `tools/server-checks.py`. It takes `get_db` and
  ten more names through `bind()` the same way, and imports nothing: an
  Engineer carries no asset identity, so unlike `register_transactions.py` it
  has no other register to ask. `_KEEP` goes the other way — a sentinel
  compared by identity, defined beside the `_save_member` signature that
  defaults to it and imported back into `server.py`, because one bound after
  import would leave those defaults holding a different object than callers
  compare against.
- `server_mail.py` — mail and the notification rules (#224): the SMTP
  settings, the one stored password, the send that never waits, and the rules
  that decide which System Log entry reaches a mailbox. Called from
  `server.py`'s three `/admin/mail*` and `/admin/notify_rules` routes, from
  `server_gui.py`'s Mail Settings and Notification Rules windows as
  `S.<name>`, and directly by `tools/server-checks.py`. It takes eight names
  through `bind()` the same way — two of them `_secret_set` and
  `_secret_get`, which stayed in `server.py` because the external asset
  system's credential is their other caller. `_KEEP` it imports from
  `register_engineers` rather than taking through `bind()`, for the reason
  that module defines it: `_save_mail_settings` defaults to it and a default
  is evaluated at import, before any `bind()` has run.
- `server_sync.py` — the external asset system (#225): the one-directional
  read of another system's asset list and the reconcile that folds it into
  the Assets register, with the three wrappers that name `sync_secret.dat`.
  Called from no route at all — `server_gui.py`'s Asset Sync window calls
  all of it as `S.<name>`, `_start_background_jobs` starts `_sync_loop`,
  and `tools/server-checks.py` drives it against a stubbed opener. It takes
  fifteen names through `bind()` the same way, two of them the
  `_secret_set`/`_secret_get` pair `server_mail.py` also takes. One of the
  fifteen is `db_path`, and it is handed over as a **callable** rather than
  the path: `DB_PATH` is resolved at `server.py`'s import and re-pointed by
  the gate between check groups, so a copy taken at `bind()` would be the
  path as it was then. `_sync_admin_cfg` stayed in `server.py` — it shares
  the prefix and nothing else, being the helper that re-reads
  `admin_config.json` where a second process has written it.
- `server_clients.py` — the registry of installations (#226): what every
  Client machine says about itself and what may be said back to it — the
  check-in, the command vocabulary and the queue behind it, the registry as
  the console reads it, and the stale sweep. **The five `/clients*` routes
  stayed in `server.py`.** This was the one of 046's six clusters whose
  routes sat inside its own banner rather than down in the Routes section,
  and the banner was split where the first `@app.route` starts — a module of
  what the routes call, not of the routes, which is the shape 041-043 took
  and what keeps `@app`, `@door` and `jsonify` out of the file. Seven names
  come through `bind()`, and that call sits below `_since_ts` rather than
  beside the other five: it is the last of the seven to be defined, and a
  name handed over before it exists is this pattern's one real failure
  mode. Two of the seven are `_member_row` and `_member_row_by_id`, bound
  rather than imported from `register_engineers` so the check-in resolves an
  Engineer against whichever register the `server.py` that bound this module
  is holding.
- `server_log.py` — the System Log (#227): the one writer every act in
  this build passes through, the words a row reads as, the readers the
  console's System Log window draws with, the clear behind its button, the
  batch a Client ships, and the two retention bounds with the hourly job
  that applies them. **`POST /clients/log` stayed in `server.py`** and
  calls `_record_log` in, which is the shape #226 gave the `/clients*`
  routes and what keeps `@app`, `@door` and `jsonify` out of the file.
  Three names come through `bind()`, and that call sits **above** the
  block that binds `server_cert`, the three registers and `server_gui`
  rather than inside it: every one of those is handed `_log_event`, and a
  name handed over before it exists is this pattern's one real failure
  mode. One of the three is `db_path`, a **callable** for
  `server_sync.py`'s reason. `EVENT_SENTENCES` moved with it, so the
  `CLAUDE.md` cascade row for a `_log_event` call names this file now.
- `server_archive.py` — backup, restore, the schema migrations and the
  archive (#228): a copy of this install and putting one back
  (ADR-0019), the migration engine `tools/*.ps1` drive through
  `AssetServer.exe migrate`, and the record archive the console exports
  and imports. Called from `server.py`'s `POST /records/import` and its
  `migrate` verb, from `server_gui.py`'s Backup and Restore window and
  its Manage Records as `S.<name>`, and directly by
  `tools/server-checks.py`. **No route moved with it** — there is no
  `@app.route` in the lifted block at all, so unlike #226 there was no
  banner to split. Twelve names come through `bind()`, one of them
  `db_path`, a **callable** for `server_sync.py`'s reason. The three
  `os.path.join(BASE_DIR, ...)` constants the block defined —
  `MIGRATIONS_DIR`, `RESTORE_ASIDE_DIR` and `CERT_ROLLBACK_DIR` —
  **stayed in `server.py`**: computed inside `bind()` they would drop
  out of `tools/cascade-audit.py`'s `BESIDE_MODULES` scan, which reads
  module-level joins to check a name written beside the app is tracked
  or ignored.
- `server_lookup.py` — the asset lookup's write path and the proposals
  (#229): the embedded sheet a first run writes, the workbook both
  directions of the interchange format use, the column mapping and the
  row verdicts an import is decided by, the proposals a Client raises
  and the Admin answers (ADR-0017), and the three readers every caller
  asks what the sheet says. Called from `server.py`'s nine `/lookup*`
  and `/asset*` routes, from `server_gui.py`'s Manage Assets and Asset
  Proposals as `S.<name>`, and directly by `tools/server-checks.py`.
  **No route moved with it.** Five names come through `bind()` and none
  is a callable — nothing on the list is re-pointed between check
  groups. It **imports `register_assets`** for `_save_asset`,
  `_load_assets` and `_IDENTIFIER_TAKEN` rather than taking them over
  `bind()`, the way `register_transactions.py` takes `_asset_key_sql`:
  three reads into that register and none into
  `register_transactions`, which is what makes this a module beside
  them and not a second interface onto them.
  `DEFAULT_LOOKUP_B64` stayed in `server.py` (rule 11) and arrives
  here over `bind()`.
- `storekeeper_app.py`, `notifier_app.py`, `installer.py` — one app each, one window each.
- `notifier_pending.py` — the Notifier's Pending decisions, below the window (#208):
  what a Confirm or a Reject means, the offline hold, and the order the popup queue is
  drained in. It returns what should happen and `notifier_app.py` performs it, which is
  what lets `tools/client-checks.py` assert all of it with no display. One app's second
  module rather than `common.py`: the Storekeeper has no pending queue, so nothing there
  would share it.
- `notifier_remote.py` — the Notifier's Remote Admin surface, below the tray menu
  (#218): the window a capability password opens and the seven panels behind it,
  moved out of `notifier_app.py` verbatim. It reaches back the way `server_gui.py`
  reaches into `server.py` — `notifier_remote.bind(sys.modules[__name__])` at import
  and `N.<name>` at every reference — because an `import notifier_app` under
  `runpy.run_path` would start a second tray client rather than reach the one
  running. The palette is the one name not reached that way: `ui_kit.Theme` binds
  the colours into an app's module globals, so `bind()` seeds this module's from the
  live palette and hands that seeding to `THEME.watch()`. One app's second module for
  `notifier_pending.py`'s reason — the Storekeeper has no console to reach.
- `storekeeper_export.py` — the Storekeeper's export (#219): the dialog that picks a
  date range and the workbook writer behind it, moved out of `storekeeper_app.py`
  verbatim. Same wall and same shape as `notifier_remote.py` —
  `storekeeper_export.bind(sys.modules[__name__])` at import, under the `THEME` — but
  it reaches back for the **palette alone**: the nine other names the moved code reads
  are imports rather than state, so it imports them itself rather than borrowing that
  app's import list through `S.<name>`. One app's second module for
  `notifier_pending.py`'s reason — the Notifier has no store to export.
- `common.py` — the wire layer the three *clients* share: pinned-certificate session,
  port-change cascade, certificate refresh, password check, update state, client identity,
  each app's config.json read over its own defaults, and the client package check.
  The server does not import it, on purpose.
- `ui_kit.py` — the buttons, the palette and the app icon the three windows
  share. A depth layer stood beside it in `ui_glass.py` from #222 until 074
  deleted it: every window here is drawn on flat colour now, and the argument
  is ADR-0022. `HAS_PIL` lives in this file, pillow's one reader left, so this
  is the flag a gate driving the no-pillow pass has to set. `run_tray_icon`
  (#271) builds and runs a `pystray` tray icon from a title, a tooltip, an
  icon image and a list of `(label, callback)` items, marshalling each
  callback onto the caller's Tk thread through `root.after(0, ...)`; `HAS_TRAY`
  lives beside `HAS_PIL` for the same reason, and a caller with neither still
  starts.
- `tools/` — PowerShell and Python for building, deploying, vendoring, checking.

What a command *does* stays in the app, not in `common.py`: closing a tray app and
closing a window are not the same act. Code moves into `common.py` only when a second
app needs the same answer, and the module docstring records why it moved.

## Headless safety

`server.py`, `server_gui.py`, `server_cert.py`, `register_assets.py`,
`register_transactions.py`, `register_engineers.py`, `server_mail.py`,
`server_sync.py`, `server_clients.py`, `server_log.py`,
`server_archive.py`, `server_lookup.py`, the nine `gui_*.py` window
modules and `ui_kit.py`
must stay importable on a machine with no display and in session 0. Every `tkinter` import sits inside
the function that draws, never at module top. Same for anything that needs a
window handle.

`notifier_pending.py` is the same rule reached from the client side and held harder:
it imports no `tkinter` anywhere, top or inside a function, and no transport either.
That is what lets a gate assert the Notifier's Pending decisions with no display
rather than by measuring a real window (#208) — `tools/client-checks.py` asserts the
import list exactly, so a new import there is a failure rather than a slow drift.

## Optional dependencies

Wrap in `try/except ImportError` and set a `HAS_*` flag; every call site checks the flag
and degrades. Applies to `pywin32` (service mode), `pystray`/`PIL` (tray). A missing
optional dependency must never stop the app starting.

## Under pythonw.exe there is no console

Source mode has no stderr. Startup failures end in a message box and a line in
`launch.err.log` — see `applaunch.py` and `docs/runbooks/source-mode.md`. Never add a
startup path whose only report is a traceback to a console nobody is reading.

## Paths

`SSL_CERT_PATH`, `UPDATE_STATE_PATH` and their kin resolve next to the running exe when
frozen and next to the source file otherwise, so a staged dev copy and an installed exe
behave the same. Use the existing resolver; do not hardcode an install directory.

## Editing these files

`core.autocrlf` is true, so the working tree is CRLF while git's blobs are LF. A tool
that writes bare LF therefore rewrites **every line** of the file as far as git is
concerned, and the one-line change is buried in a whole-file diff nobody can review. So
an edit to a Python source here goes through a short patch script written into the
scratchpad — authored with the file-writing tool, never `python -c` and never a heredoc
carrying the payload, since both go through a shell that eats backslashes and quotes.
The script is the same four things every time:

```python
import ast, io

CR = chr(13) + chr(10)
src = io.open(PATH, encoding="utf-8", newline="").read()

def sub(old, new):
    global src
    assert old != new                      # a no-op sub reports success
    old = old.replace(CR, chr(10)).replace(chr(10), CR)
    new = new.replace(CR, chr(10)).replace(chr(10), CR)
    got = src.count(old)
    assert got == 1, "expected 1, got %d" % got
    src = src.replace(old, new, 1)

... subs ...

data = src.encode("utf-8")                 # encode *before* truncating the file
with io.open(PATH, "wb") as f:
    f.write(data)
b = io.open(PATH, "rb").read()
print("CRLF", b.count(b"\r\n"), "LF", b.count(b"\n"))
ast.parse(b.decode("utf-8"))
```

Each of those is a failure that has happened here rather than a precaution.
**Normalising both sides** is what lets an anchor copied out of a file read (which
strips the CR) match the file on disk. **`count == 1`** is because a duplicated anchor
edits whichever copy comes first, silently and usually not the one that was meant.
**`old != new`** is because a `sub` that changes nothing passes the count assertion and
reports a patch that did not happen — which is how one fix was applied twice and landed
neither time. **Encoding before the open** is because an encoding error after
`open(..., "wb")` has already truncated the file leaves nothing behind at all. And the
two counts being **equal** is the whole proof that the line endings survived; print them
even when the file is Markdown, where there is no `ast.parse` to stand in for it.

Read the patch script end to end before running it. The anchors are the part that goes
wrong, and they go wrong quietly.

`tools/*.ps1` are the one set of files this does not cover: they stay **pure ASCII**
whatever writes them (Windows PowerShell 5.1 reads a BOM-less file as cp1252, where an
em-dash's trailing byte becomes a smart quote and breaks parsing). Python under `tools/`
and Markdown anywhere are exempt from that and are not exempt from the CRLF rule.

## Comments and docstrings

- A module docstring says what the module is for, and — where the module exists because
  of a problem — what the problem was. `common.py` records that its parts were
  byte-identical copies kept in sync by hand; that is the standard to match.
- Comments justify a decision, a refusal, or a deliberate omission. Not a narration of
  the next line.
- A change that contradicts an ADR updates the ADR or does not happen.

## Naming and style

- `snake_case` functions, `_leading_underscore` for module-private helpers
  (`_make_server_tray_icon`, `_launched_by_scm`, `_payload_mode`), `UPPER_CASE` constants.
- New code: one import per line, standard library first. `server.py` still has
  comma-grouped imports and lines past 200 columns — that is history, not the target;
  new and touched code wraps near 100.
- Anything the installer or the server decides by *looking at what is there* stays that
  way (`_payload_mode` reads what sits beside it, never a flag), so it cannot be told to
  do something that was never shipped.

## Tkinter windows

**This section governs all four apps**, not only the Server GUI. The Server GUI
is where the defect was found and measured first, but every window in this
build is drawn out of the same kit and loses the same control when one is too
small: `server_gui.py`, which is the console `server.py` held until #207, the
Storekeeper over `storekeeper_app.py` and `storekeeper_export.py`, the Notifier
over `notifier_app.py` and `notifier_remote.py`, and `installer.py`. Fourteen
windows were too small, and the client half had no gate on it at all until
`client-checks.py`.

- **A window is never smaller than its own children.** That is the rule; there
  are two ways to keep it. A form that grows - one where a field is likely to be
  added - calls `ui_kit.fit(win, width)` once every child is packed: it takes
  the height from `winfo_reqheight()`, the width from whichever of the argument
  and `winfo_reqwidth()` is larger, clamps the height to the screen, and lowers
  a written `minsize` height that would otherwise put the shortfall back (`wm`
  honours a minimum even on an axis it will not let anybody drag). There is one
  of it, in `ui_kit.py`, called from the Server GUI and both clients; it lived
  in `server.py` as `_fit` until the clients needed the same answer, and rule 10
  is why it moved rather than being copied. A window whose contents are settled
  may keep a written size, as six in the Server GUI do, but then it is the
  writer's job to keep it larger than the form. Fourteen had not: a written size
  is a second copy of a number the children already know, and it is the copy
  that goes stale.
- **Never make the size conditional.** `440x%d % (370 if needs_pw else 300)` was
  wrong by a different amount in each branch, and no sweep for geometry strings
  could see it. There were three: the Server GUI's Cancel Transaction, the
  Storekeeper's, and the Notifier Dashboard's `1140x740 if see_all else
  1080x740`. If the size depends on what is in the window, ask the window -
  except where the window cannot answer, which the Dashboard is: a Treeview's
  request excludes its own column widths and comes back at 449px, so that one
  takes the wider branch unconditionally and leaves both axes draggable. Either
  way the `if` goes, and `client-checks.py` fails an `IfExp` inside a
  `geometry()` argument outright.
- **Pack the buttons into a `side="bottom"` frame before packing the form.**
  `pack` gives a shortfall to whichever child was packed last, so a button
  packed last is the control that disappears - and it disappeared four times
  here, including Add Transaction's submit button and Capability Passwords'
  Close - and twice more in the clients, where the Storekeeper's Admin Login and
  the Notifier's each showed 1px of a 46px Login button. Sizing to the request
  makes that rare, not impossible: a screen shorter than the dialog cannot be
  argued with, which is why the footer is packed first as well. That is checked
  by forcing the window shorter than its form and asserting the bottom control
  is still mapped, on the screen and button-sized - `server-checks.py` does it
  for Add Transaction, `client-checks.py` for every dialog that calls `fit`.
- A window meant to be resized says so with `resizable(True, False)` and a
  `minsize`, the way `change_display_settings`, the client dialogs and the
  elastic toolbar rows do. `client_list` and `manage_records` are tables and
  leave both axes free, as do the Notifier Dashboard and the client windows that
  make no `resizable` call at all. Everything else in the Server GUI is
  `resizable(False, False)`, which is what makes the rules above load-bearing
  rather than cosmetic: there is no drag to recover with. **Judge each axis only
  where that axis is fixed** - a shortfall on a resizable one costs a drag, not
  a control, and both gates report it as such rather than failing. A `minsize`
  is not the escape it looks like: `wm` honours it on a fixed axis too, so a
  `minsize` height above the form's is the same stale number one level down.
- **Measure inside the real window.** `tools/server-checks.py` opens the Server
  GUI through `gui_root()` and `tools/client-checks.py` builds each client app
  the way its entry point does; both read sizes back off the screen. A dialog
  built under a bare `tk.Tk()` misses the ttk styles and fonts the app
  configures at startup and reports 24px less than a user sees, which is how a
  wrong number got into three docstrings and an issue.

### A list is real widgets, not a `ttk.Treeview`

**Every list built from 076 on is a scrolled frame of real rows**, and the one
in `ui_kit.ListPane` is the shape they are built out of. This is decided here
rather than per window because the list-and-detail shape is what every window
after 076 is made of, and the tickets that build those windows each add four
more lists.

The first reason is that the row this material asks for is not a row a Treeview
can draw. It is two lines - the Asset Number in `code` at 13 with the Serial
Number under it in `code_lg` in `SUBTEXT`, rules 3 and 4 - with the direction
word and the state right-aligned against the pair and a 3px direction gutter
beside the lot. A Treeview gives one font, one foreground and one height per
row, through tags, and no way to colour part of one; two lines in two faces
with a third colour beside them is four things it does not have.

The second is the half that would not have been found by trying it: a Treeview
takes its heading, its row height, its selection fill and its focus ring from
the `clam` theme engine and not from a token. The 064 contrast floor is held by
`tools/palette-contrast.py`, which walks the palette tables - so a colour the
theme engine chose is a colour that gate cannot see, in either theme, and the
window where the floor matters most is the one that is nothing but rows.

What it costs is written down rather than discovered later: a frame of real
rows has no column sorting, no keyboard navigation and no virtualisation, so a
list of ten thousand rows is ten thousand widgets. The first two do not exist
on any of these lists today and the console's feed is bounded by a setting
(5-200 rows). **A list that is genuinely a table stays a Treeview** - Manage
Transaction History sorts by column and multi-selects, and Delete acts on that
selection - and none of the 47 Treeviews in this build is being converted by
this decision. It says what a *new* list is.

The console's activity feed was already built this way before 076 named it, and
`ui_kit.ListPane` is where that shape now lives. The two `_ScrollArea` classes
that predated it are both gone, each with the list it was holding - the Server
GUI's with the feed at 076 and the Notifier's with the Pending cards at 079 -
so the shape below this paragraph is the only scrolled list of rows in this
build; the other hand-rolled regions, which are not lists, are left alone.

## The database

SQLite on the server only. Clients never open it; they go through the API. A cancelled
transaction is kept, not deleted (ADR 0003). The database can be moved, but only
deliberately (ADR 0004).

## Tests

- `tools/server-checks.py` — the suite, `check`-style with PASS/FAIL counters, no pytest.
- `tools/client-checks.py` — the same idiom for the three client apps' windows: it stages
  copies of their sources, opens each app offline and measures every window against its
  own form. Its own suite rather than more groups in `server-checks.py`, which is
  server-shaped from its first line — every helper there takes a database.
- `tools/deploy-checks.ps1` - the same idiom again for the deployment helpers in
  `tools/_deploy.ps1`, and PowerShell rather than Python because what it drives is
  PowerShell. No Pester, for the reason the two above carry no pytest. It exists because
  `install-iis.ps1` stands up IIS and cannot be run by a gate at all: a decision in it
  that has to be *run* rather than read moves into `_deploy.ps1`, which every script here
  dot-sources, and is driven from there.
- New behaviour on the server or the wire gets a check in the same change; a bug fix gets
  the check that would have caught it.
- `tools/gate.py` picks which of those four a change owes and runs them in parallel.
  It is not a gate itself; it is what stops a docs commit paying for all four.
- `tools/dev-run.ps1` stages the apps for a real run; `tools/cascade-audit.py` checks the
  port-change cascade.

### What an assertion has to be

- **Every new assertion carries a negative half.** A check that can only pass by
  finding nothing is worse than no check, because it reports a clean run for ever.
  `cascade-audit.py`'s own docstring records that twice, and `client-checks.py` met it
  again at #161: `measure_scrolled_body` matches only a `tk.Frame` windowed into a
  `tk.Canvas`, so converting the installer's scrolling body would have turned three real
  measurements into a group that measures nothing and still prints green. **Before
  converting a container, grep the gates for a `winfo_class()` filter over it** — those
  filters are what a layout change is invisible to.
- **Assert a measurement, not a restatement of the code.** A selection state read back
  as the face the code just wrote is the code agreeing with itself. Express it as
  something the user could see — the `alpha`, or the border — and compare the subjects
  **with each other**, read off the widgets: the installer's three cards are asserted to
  be three colours rather than each asserted to be the colour it was assigned, which is
  what caught a selection that had no visible effect at all.
- **A size you asked for is not a size the window has.** `wm geometry` is a
  request; the window manager grants it when it gets round to it, and
  `update_idletasks()` plus `update()` return before that - they flush what Tk has
  queued, not what the WM has yet to do. So a read taken straight after a resize can
  have the **old** width against the **new** content and report a shortfall that is a
  race. #204 is what that costs: three runs of one group alone in one process came
  back green, red, green, and the same leg reported 67, 64, 60, 58 and 56px on
  different runs of unchanged code. Worse than the noise, the *green* runs were the
  wrong ones - there was a real clipped control under it that the unsettled read kept
  missing. Settle after a resize until **the reading repeats**, not until a clock says
  so: take the measurement each pass and stop when it comes back the same twice, with
  a bound, because a window manager that will not grant the size is something to
  report rather than hang on.
- **Settle a Tk window before reading anything off it.** `Surface` arms its render
  behind `after(60, ...)` off the `<Configure>` Tk sends on mapping, so a loop of
  `update()` returns long before it fires and every assertion reads an unrendered
  window. Use `root.update_idletasks(); root.update(); root.after(250, root.quit);
  root.mainloop()`. A widget that has not been laid out reports 1x1 at its parent's last
  position, and a crop taken from off the ground comes back near-white rather than
  missing — which is what "something other than CARD" passes on.

### Running them

`py -3.12 tools/gate.py` is the normal way to run them: it runs the suites the diff
can reach, shards the two long ones across cores, and sets the environment each wants.
`--all` is the release run and what `land.py` does, and it adds `tools/upgrade-drill.py`,
which no diff owes. Run one directly while iterating on
it; run `gate.py` before calling a change done.

All five gates exit non-zero and all five run before `package.ps1`. The three Python
ones want `PYTHONIOENCODING=utf-8` and `python -u`, and the two window suites also read
`AM_GATE_OFFSCREEN=1` - `gate.py` sets both, and `tools/_offscreen.py` is what the second
one reaches. A suite run by hand keeps its windows on the screen, which while iterating
on one is the point; the PowerShell one has to be
captured with `*>&1` **inside PowerShell**, since `Write-Host` writes to the information
stream and `2>&1` captures none of it (and in a bash shell `*` globs the working
directory into the argument list instead). The two long suites print failures and a last
line only, `-v` for every passing line.

`server-checks.py` is the long one. Background it and then **block on its content**
rather than on the shell, since a backgrounded launcher returns immediately and its
"finished" notification is the shell's rather than the gate's:

```bash
until grep -qE "all checks passed|check group|FAILURE|Traceback" "$S/srv.out"; do sleep 20; done
```

While iterating on one group, run that group alone rather than the whole suite. Both
long suites are packages, and both take `--group NAME` to select one module of
`tools/server_checks/` or `tools/client_checks/`, `--list-groups` printing the names.
`client-checks.py` also takes `--check NAME`, one `check_*` group, which was its only
selector while it was one module, with `--list-checks` beside it.

```bash
py -3.12 tools\server-checks.py --group console
py -3.12 tools\client-checks.py --group popup
py -3.12 tools\client-checks.py --check check_the_storekeeper_windows_fit
```

What that saves is the rest of the file, not the group: `--group settings` is three
seconds and `--group console` 1m58s against 5m47s for all twenty-five;
`check_the_storekeeper_windows_fit` is nine seconds against 3m01s for all sixty-nine.
The selector and `--shard` are both named on the last line of the run, because green
over part of a file is not green over the file. Neither suite will accept an argument
it does not know - a mistyped flag exits 1 with the usage rather than quietly running
everything.

Below `--group` is one check of `server-checks.py`, which has no flag and is still a
by-hand import. It is a package since #221, so loading one of its group modules by path
gets an `ImportError` on the `from server_checks.stage import ...` at the top of it:
put `tools\` on the path and import the module instead, which is what its entry point
does. `client-checks.py` has `--check` for this, and the same import works there too,
since #238 made it a package on the same pattern.

```bash
py -3.12 -c "import sys; sys.path.insert(0, 'tools'); from server_checks import console, stage; console.check_toolbar_fits(); print(stage.fails)"
py -3.12 -c "import sys; sys.path.insert(0, 'tools'); from client_checks import popup, stage; popup.check_what_the_popup_timers_may_be_set_to(); print(stage.fails)"
```

The counters are `stage`'s now rather than the calling module's, `fails` among them —
one set for each whole package, which is what lets the last line of a run count every
group's assertions in one place. And append `; true` to any `grep -c`, which exits 1
over a file with no matches and takes the whole command down with it.

**Locate a check by its `head(...)` line, never by grepping the message it prints**: the
messages are assembled from the values being measured and are not in the source as
written.

### Cascade before you gate

The documentation cascade lands **before** the gate run, not after it. `cascade-audit.py`
reads counts and claims out of `CLAUDE.md`, the reference documents beside this
one and the sources together, so a green run over
an uncascaded tree is a green run over a tree that is about to change — and the number
that moved is exactly the kind it is there to catch. A stated measurement is re-derived
by the audit rather than typed into the sentence; where the audit cannot derive it, state
it in **one** paragraph and nowhere else, so there is no second copy for the check to
have to choose between.

## Building

`tools/vendor.ps1 -Role server` and `-Role client` first, once per change to a
`requirements-<role>.txt`: each writes a `lib-<role>\` and stamps it with the Python
minor version it was built under. Then `tools/package.ps1` writes a release into
`dist\<version>\` — the server's source zip and `AssetManager_Setup.exe` — or either
alone with `-Component server` / `-Component client`.

**PyInstaller compiles one thing and it is the installer.** The four apps ship as the
`.py` files a signed `pythonw.exe` reads, so there is no app exe to build (rule 12,
rule 14). For `installer.py`'s own imports PyInstaller still follows them, so a module
*it* imports needs no entry — but a new *entry point* does.

**What an app imports is not what an install carries.** A payload here is a written-down
list, not a traced import graph, and a client's is two of them: `$Payload` in
`tools/bundle-client.ps1` is what goes into the zip and into what PyInstaller embeds,
and `SOURCE_FILES` in `installer.py` is what gets copied onto the machine. **A new
shared client module has to be added to both**, or it imports cleanly here and is
missing on an engineer's laptop — where, under `pythonw.exe`, the `ImportError` is
silent. `cascade-audit.py` holds those two equal per app, so that one is caught here
rather than on a laptop. The server's payload is a third list, `$SourceFiles` in
`tools/package.ps1`, held by nothing — it has no second copy to be held against.
