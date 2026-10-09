# 057 - The imports each lifted module left behind

**Type:** refactor - **Depends on:** 055 - **Found by:** 051 (#225) - **Issue:** [#231](https://github.com/HaithamEldesouky/AssetManager/issues/231)

## Finding

Each of 050-055 moves a cluster out of `server.py` and takes its `import` lines with it
into the new module. What none of them does is remove the copy left at the top of
`server.py`, because a stdlib import is not part of the block being moved and taking it
out is a second change in a ticket asserting a pure move.

Four are already dead, measured against `main` at `7582d60`, each appearing exactly once
in the file - its own import line:

- `import smtplib` (`server.py:18`) and `from email.message import EmailMessage`
  (`server.py:23`), left by 050 (#224) when mail became `server_mail.py`.
- `import urllib.request` (`server.py:20`) and `import urllib.error` (`server.py:21`),
  left by 051 (#225) when the sync became `server_sync.py`.

051 found the first pair while checking whether it had created the second, and followed
050's precedent rather than diverging mid-chain - which is the right call for one ticket
in a sequenced chain and the wrong end state for the file.

**Expect more by the time this runs.** 052, 053, 054 and 055 will each leave their own,
and which ones cannot be known in advance: `sqlite3`, `json`, `os`, `threading` and
`time` are shared by nearly every cluster and will still be live, while whatever a single
cluster imported alone will not. **This ticket measures, it does not carry a list.** The
four above are what was true at `7582d60` and are the example, not the scope.

## Scope

`server.py`'s import block, and the same question asked of every module the chain
created.

1. **Measure, per file.** For each of `server.py` and every `server_*.py` /
   `register_*.py` beside it, find the module-level imports no code in that file reads.
   A `symtable` sweep or an `ast` walk over `Name` and `Attribute` loads answers it;
   a text `grep` does not, because `ssl` appears 41 times in `server.py` and twice as
   code.
2. **Remove the dead ones.** Nothing else - no reordering, no regrouping, no splitting
   `server.py:12`'s one-line multi-import into separate lines.
3. **Say what was removed and which ticket left it**, per name, in the commit.

## Not in this ticket

- Any live import, however oddly placed. `server.py:12` puts eleven on one line and that
  is the file's own habit (`docs/CODING_STANDARDS.md`).
- The deferred imports inside functions - `tkinter` in the drawing functions, `ui_kit` in
  `ui_glass.panel`'s no-pillow branch. Those are load-order and headless-safety
  decisions, not leftovers.
- `requirements-server.txt`. Every name here is stdlib; nothing installed changes.
- The client modules. 044 (#218) and 045 (#219) may have left the same thing behind in
  `notifier_app.py` and `storekeeper_app.py`; measure them in step 1 and file what turns
  up rather than widening this.

## Sequencing

**Last in the chain, behind 055.** Running it earlier means running it again: each
remaining ticket leaves more. It touches no line 050-055 touch, so it is behind them for
that reason alone rather than for a cascade collision.

## Cascade

None expected - a removed stdlib import is named in no document. Confirm that rather than
assuming it: `docs/reference/architecture.md`'s `server_sync.py` row says the module
"imports no HTTP client", which is a claim about the new file and stays true, and
`docs/CODING_STANDARDS.md`'s headless-safety section names `tkinter` specifically.

## Verification

- `ast.parse()` every file edited.
- `py -3.12 tools/gate.py --all`. A dead import removed by mistake is an `ImportError` or
  a `NameError` at the first call, so the server and client suites are the test; there is
  no subtler failure mode here.
- **Import each edited module headless** and confirm it still imports. That is what an
  over-eager removal breaks first.
- Re-run the step 1 sweep and confirm it finds nothing, which is what makes this ticket
  finished rather than partly done.
