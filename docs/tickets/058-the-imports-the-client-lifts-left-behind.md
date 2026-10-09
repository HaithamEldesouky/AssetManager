# 058 - The imports the client lifts left behind

**Type:** refactor - **Found by:** 057 (#231) - **Issue:** [#232](https://github.com/HaithamEldesouky/AssetManager/issues/232)

## Finding

057 removed the imports 050-055 left behind in `server.py` and, per its own
scope, measured the client modules rather than changing them. Four candidates
turned up. Measured on `main` at `e1538d7` with a `symtable` sweep plus an
independent AST pass over `Name` and `Attribute` loads, cross-checked against a
`tokenize` pass. All three sweeps agreed.

### `notifier_app.py` - left by 044 (#218)

Three names, each dead the moment the Remote Admin surface lifted out at
`de4c18f`, and each imported independently by `notifier_remote.py` rather than
reached back through `N.<name>`:

| line | import | where the use went |
|---|---|---|
| 8 | `from tkinter import filedialog` | `notifier_remote.py:39`, used at `:775` |
| 9 | `import base64` | `notifier_remote.py:36`, used at `:790` |
| 15 | `from common import offline_url_notice` | `notifier_remote.py:42`, used at `:2204` |

`offline_url_notice` needs the same check the `server.py` re-exports needed
before it is removed: confirm nothing reaches it as `N.offline_url_notice` or
as an attribute on the `notifier_app` module. The sweep found no such site, but
that is the one shape a use-sweep is blind to - see below.

### `storekeeper_app.py`

| line | import |
|---|---|
| 12 | `import time` |

Not attributable to 045 (#219): `time.<attr>` was already absent from the file
across the last forty commits that touch it, so it predates the export lift.
Whoever picks this up should re-measure rather than inherit that sentence.

## What 057 learned the hard way

**A name with no load site in its own file can still be live.** 057 removed
`import smtplib` from `server.py` on a clean sweep and `gate.py --all` failed
four checks: `tools/server-checks.py` reaches the module object through
`M.smtplib` to put a stub SMTP in front of them. Before removing anything here,
run the same external check - is the name read as an attribute on any object,
or named in a string, anywhere in the repo outside its own module? -
over `tools/client-checks.py` in particular.

`tools/client-checks.py` also asserts `notifier_pending.py`'s import list
exactly (`docs/CODING_STANDARDS.md`, headless section). That file is clean and
must stay untouched.

## Scope

1. Re-measure `notifier_app.py` and `storekeeper_app.py`, and the external
   attribute/string check above, at whatever `main` is then.
2. Remove the dead ones. Nothing else - no reordering, no regrouping.
3. Say what was removed and which ticket left it, per name, in the commit.

## Not in this ticket

- Any live import, however oddly placed.
- Deferred imports inside functions. Those are load-order and headless-safety
  decisions.
- `ui_kit.py:1758`'s block of 34 names from `ui_glass.py`. Those are the
  deliberate re-export surface #222 created so every caller still says
  `ui_kit.Surface`; `CLAUDE.md` says so outright. Not a leftover.
- The seventeen unread re-exports in `server.py` - a separate question, and a
  public-surface change rather than a leftover.

## Cascade

None expected - a removed stdlib import is named in no document. Confirm it
rather than assuming: `docs/CODING_STANDARDS.md`'s headless section names
`tkinter` specifically, and `notifier_app.py:8` is a `tkinter` import, so read
that sentence before touching it.

## Verification

- `ast.parse()` every file edited.
- `py -3.12 tools/gate.py --all`. An over-eager removal is an `ImportError` or
  a `NameError` at the first call; the client suite is the test.
- Import each edited module headless and confirm it still imports.
- Re-run the sweep at the end and confirm it finds nothing.
