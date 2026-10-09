# 056 - `SHIPS` names no register module, and a package manifest goes stale unreported

**Type:** bug - **Depends on:** 055 (cascade line only) - **Found by:** 050 (#224), re-found by 051 (#225) - **Issue:** [#230](https://github.com/HaithamEldesouky/AssetManager/issues/230)

## Finding

`tools/cascade-audit.py`'s `SHIPS` (`tools/cascade-audit.py:1448`) is the regex that
decides whether a commit made since a built package's manifest touched anything that
package actually contains. Its own comment says what it is for: "A manifest behind HEAD
is drift only if a file that actually ships changed in between. A docs-only commit does
not invalidate a package."

It names `server.py`, `server_gui.py`, `storekeeper_app.py`, `storekeeper_export.py`,
`notifier_app.py`, `notifier_pending.py`, `notifier_remote.py`, `installer.py`,
`common.py`, `ui_kit.py`, `ui_glass.py`, `applaunch.py`, `server_mail.py`,
`server_sync.py`, `run_*.pyw?`, `migrations/` and `requirements-`.

**It names none of the three registers.** `register_assets.py`,
`register_transactions.py` and `register_engineers.py` are all in `$SourceFiles` at
`tools/package.ps1:149` and all three ride in the server zip -
`docs/reference/tooling.md` lists them in the payload sentence in as many words.

So a commit that changes one of the three and nothing else leaves a built server package
**reported as current** while the code inside it is a version behind. That is the exact
failure this check was written to catch, pointed at three of the files it is meant to
cover. Nothing else catches it: `package.ps1` re-stamps a manifest when it builds, and
the only thing that compares a built manifest against `HEAD` is this regex.

It is not a new gap. 041-043 (#215, #216, #217) created the three files and did not add
them; 050 (#224) added `server_mail.py` beside them and left the hole alone as out of
scope; 051 (#225) added `server_sync.py` and did the same, and said so in its report.
Two tickets have now walked past it, which is what makes it a ticket of its own rather
than a line in the next one.

## Scope

One line of `tools/cascade-audit.py`.

1. **Add the three registers to `SHIPS`** - `register_assets\.py`,
   `register_transactions\.py` and `register_engineers\.py`, beside `server_mail\.py`
   and `server_sync\.py`.
2. **Derive rather than list, if that is cheaper than it looks.** `SHIPS` is a hand-kept
   copy of what the packages ship and `$SourceFiles` is the other copy - the shape rule
   10 exists to prevent, and the reason this has drifted three times. A `SHIPS` read out
   of `tools/package.ps1`'s `$SourceFiles` and `tools/bundle-client.ps1`'s `$Payload`
   would make the next module impossible to forget. **Check it, do not assume it**: both
   are PowerShell arrays inside scripts this file does not otherwise parse, and a parser
   for them is a second thing to get wrong. Where the read is more than a few lines, take
   step 1 and record the reasoning in the commit rather than building it.

## Not in this ticket

- Any change to what the packages ship. `$SourceFiles` and `$Payload` are right; the
  regex reading them is what is wrong.
- `_EVENT_SOURCES`, `BESIDE_MODULES` and `_FIT_APPS`, the three other lists in this file.
  All three are correct for the registers as they stand.
- Rebuilding or re-stamping any package. There is no `dist\` on the machines this was
  found on, and the check notes that and skips.

## Sequencing

**Behind 055.** Each of 052, 053, 054 and 055 adds its own module name to this same
`SHIPS` regex, which is the `tools/package.ps1:149` trap one file along - two tickets
rewriting one line cannot merge. This one goes in after the last of them, and if step 2
is taken it deletes the line all four of them will have edited.

## Cascade

- `docs/reference/tooling.md`'s `cascade-audit.py` section, where the manifest check is
  described.
- **Not** the Cascade table in `CLAUDE.md`: its row for `a tools/*.ps1 behaviour` is about
  the scripts, and this is the audit reading them. Consider whether that table wants a row
  saying a shipped module must reach `SHIPS` - a fourth ticket walking past this gap is
  the argument for one.

## Verification

- `py -3.12 tools/gate.py` - the cascade gate runs this file.
- **Drive the check at the failure.** Build a server package, commit a one-line change to
  `register_engineers.py`, and confirm the audit now reports that manifest as drifted
  where before it reported it current. That is the whole of what this ticket buys and the
  only test that shows it.
- Confirm a docs-only commit still does **not** report drift. This regex's purpose is as
  much about what it excludes as about what it names.
