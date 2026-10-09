# 049 - The instructions stop describing the apps as flat single files

**Type:** docs · **Depends on:** 035, 036, 037, 038, 039 (or its successors 041-043), 040, 041, 042, 043, 044, 045, 046, 047, 048, 050, 051, 052, 053, 054, 055 · **Found by:** architecture review, Sep 2026 · **Issue:** [#213](https://github.com/HaithamEldesouky/AssetManager/issues/213)

## Finding

`docs/CODING_STANDARDS.md:3-5` says "The four apps are flat modules at the repo root", and
its "Where code goes" section (lines 12-26) is a list of files rather than a rule for where
a new module belongs. `CLAUDE.md`'s "The files" table and `docs/reference/architecture.md`
describe the same layout. Once the chain this ticket depends on lands - `server_gui.py`
and `server_cert.py` already out (035, 036), `register_assets.py`/
`register_transactions.py`/`register_engineers.py` out (041-043), whatever 046's clusters
and 047's package add, `notifier_remote.py` and `storekeeper_export.py` out (044, 045),
`ui_glass.py` out (048) - those sentences describe a tree that no longer exists. A reader
who opens `CODING_STANDARDS.md` before the codebase gets told something false on line 3.

## Scope

Docs only.

1. **Replace "flat modules" with the principle the chain actually followed**: one module
   per concern, a deep module (small interface, most of the behaviour behind it), no copy
   of a shared helper (rule 10), nothing added for a requirement that does not exist yet.
   State how a module reaches back to the program that owns it - the `bind()` pattern
   `server_cert.py` set and every later module in this chain repeated, because
   `applaunch.py` runs each app as `__main__` through `runpy.run_path`, so a plain
   `import server` (or `import notifier_app`, or `import storekeeper_app`) from a helper
   module would start a second copy of the whole program rather than reach the one already
   running.
2. **Turn "Where code goes" into a rule plus the current table** - the table lists every
   module this chain added (035-048), not the four flat files it used to. Add the cascade
   row a new module owes, matched against what this chain's own tickets actually touched:
   `$SourceFiles` in `tools/package.ps1`, `tools/dev-run.ps1`'s staged lists,
   `tools/server-checks.py`'s staging tuple, `tools/gate.py`'s `MAP` (server side); `$Payload`
   in `tools/bundle-client.ps1`, `SOURCE_FILES` in `installer.py`, `tools/client-checks.py`'s
   staging block, `tools/gate.py`'s `MAP` (client side). Add this row to the cascade table
   in `CLAUDE.md` and to `docs/reference/cascade.md`.
3. **`docs/reference/architecture.md` and `docs/reference/apps.md`** - re-derive every
   stated count (line counts, function counts, call-site counts) against the tree this
   chain leaves behind rather than copying any number forward from an earlier ticket's
   Finding section, including this file's own.

## Not in this ticket

- Any code. Nothing here moves a line of Python.
- Filing any further split. If the review that produced this chain surfaces another
  module worth lifting out, that is its own ticket, found the same way 044/045 were found
  from a comment on #208.

## Cascade

- `CLAUDE.md` - "The files" table becomes the full post-chain table; the cascade table
  gains the "a shared client module"/"a new module" rows this ticket's Scope §2 describes,
  matched against what 035-048 actually cascaded rather than restated from memory.
- `docs/reference/cascade.md` - the same row.
- `docs/reference/architecture.md`, `docs/reference/apps.md` - every stated count
  re-derived, per Scope §3.
- `docs/CODING_STANDARDS.md` - "flat modules" (lines 3-5) and "Where code goes"
  (lines 12-26) rewritten per Scope §1-2. Re-read both against the tree at the time this
  ticket is worked; line numbers cited here are what the current tree shows and are
  expected to have moved once 035-048 have landed ahead of this one.
- `tools/cascade-audit.py` - confirm it reads the docs above rather than a stale count, and
  that its checks still pass once "flat modules" is gone; a check asserting the old
  sentence word-for-word would need to change with it.

## Verification

- `py -3.12 tools/gate.py` - the cascade-audit gate, which reads every document under
  `docs/` and `CLAUDE.md`, must stay green: this ticket's whole point is that prose and
  tree agree.
- Read `CODING_STANDARDS.md` top to bottom once done and confirm nothing on it still says
  "flat" or names a file this chain moved code out of without saying where the code went.
