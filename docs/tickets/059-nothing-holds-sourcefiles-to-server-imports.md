# 059 - Nothing holds `$SourceFiles` to what the server actually imports

**Type:** bug - **Depends on:** 056 (#230), merged - **Found by:** 056 - **Issue:** [#233](https://github.com/HaithamEldesouky/AssetManager/issues/233)

## Finding

`tools/package.ps1`'s `$SourceFiles` is what the server zip contains. Nothing asserts it
holds every module the server imports, so a new `server_*.py` that `server.py` imports at
module level and that nobody adds to that list is not packaged - and the server dies on
its own import line on the machine it was installed to, under a service host with no
console, saying nothing a reader can act on.

Every neighbouring copy of "what a component consists of" is already held to something:

- `dev-run.ps1`'s own server list is checked against `server.py`'s imports
  (`cascade-audit.py`'s "dev-run.ps1 stages what the apps actually import").
- `bundle-client.ps1`'s `$Payload` is checked against `installer.py`'s `SOURCE_FILES`
  ("the two client payload lists agree").
- Every name either release script states is checked to be a file git tracks
  ("the release scripts name only committed files").

`$SourceFiles` is in that last one, which asks whether the names in it exist - never
whether the names that should be in it are. It is the one copy with no check pointing at
its contents, and it is also the copy 056 (#230) made `SHIPS` derive from: a module
missing from `$SourceFiles` is now invisible to the manifest drift check too, so the same
omission costs the package AND the check that would have reported the package stale.

`dev-run.ps1`'s list is the near miss that makes this reachable rather than theoretical.
Adding a server module there is what makes the dev harness run, so that is the list a
developer edits first and the one the existing check rewards. `$SourceFiles` is edited
only at packaging time, by whoever is doing the release, which is not the same sitting.

## Scope

One new check group in `tools/cascade-audit.py`, beside the dev-run one it is modelled
on, reusing that check's `_module_imports`.

- Walk the module-level import closure of the server's two roots, `server.py` and
  `run_server.py`, over files that exist in this repo.
- **Fail** on a module in the closure that `$SourceFiles` does not name: that file does
  not ship and the install dies on the import.
- **Note** a name in `$SourceFiles` that the closure does not reach: either dead weight
  in the zip or a lazy import this cannot see. Worth a reader, not worth a red gate.

Transitive rather than one level, which is where this differs from the dev-run check it
copies. `ui_glass.py` is the case that proves it: no app names it, `ui_kit.py` imports it
at the foot of its own body, and a zip with the kit and no glass dies on the kit's import
line, silently, under `pythonw.exe` (#222).

The closure and `$SourceFiles` are **equal** today, 16 names each, both directions empty.
The check therefore starts green and states a property that currently holds, rather than
reporting a backlog.

## Not in this ticket

- The client half. `$Payload`, `$Apps.<key>.Extra` and `installer.py`'s `SOURCE_FILES`
  already hold each other, and the dev-run check covers the client apps' imports. A
  closure check pointed at the client zip is a second ticket if it is wanted at all.
- Any change to `$SourceFiles` itself, or to what the packages ship. The list is correct;
  what is missing is the thing that says so.
- `SHIPS`, `_EVENT_SOURCES`, `BESIDE_MODULES`, `_FIT_APPS`.

## Cascade

- `docs/reference/tooling.md`'s `cascade-audit.py` section - a new check group belongs in
  the list of what that script holds.
- `docs/tickets/README.md`'s table.
- **Not** `CLAUDE.md`'s Cascade table. The row this would want - "a new server module
  must reach `$SourceFiles`" - is what the check now enforces, and the table records
  couplings a reader has to keep by hand.

## Verification

- `py -3.12 tools/gate.py` green, and the new group reporting the equality rather than
  skipping.
- **Drive it at the failure.** Remove a module from `$SourceFiles` and confirm the group
  names that module and fails; restore it and confirm green. Do the same for a module
  reached only transitively (`ui_glass.py`) to show the closure is not one level deep.
- `py -3.12 tools/server-checks.py` - record the "N check group(s), M assertion(s)" line
  before branching and match it at the end.
