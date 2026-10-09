# 033 - The exe and the service take the new name

**Type:** refactor (cutover) · **Depends on:** 023 · **Runs last** · **Needs a runbook**

## What changes

023 renamed the words. This renames the identifiers: `AssetServer.exe` (37 references
across `*.py` and `tools/*.ps1`), the `AssetManagerServer` Windows Service (22), the IIS
site and app pool names, `web.config`'s `processPath`, and the PyInstaller spec names in
`tools/package.ps1`.

## Why it is separate, and why it is last

Every one of those names is written down on a machine this repo does not control:

- `update.ps1` stops a service **by name** and writes `rollback/<version>/` beside an exe
  **by name**; a renamed exe makes the installed rollback set unusable by the new script
  and the new set unusable by the old one;
- `install-iis.ps1` wrote `iis.json` recording the site and pool it bound, and `_iis_host()`
  reads it - a renamed pool makes the Server GUI's banner name a pool `Stop-WebAppPool`
  cannot find, which is exactly the defect the banner was added to fix;
- a client resolves nothing by exe name, so the fleet is safe - but the **server machine**
  needs a re-install, not an update.

So this is a cutover with a runbook, run deliberately on a chosen day, and it is last
because every ticket between 024 and 032 would otherwise be rebased across a rename of the
file they all edit.

## Shape of the work

- **Both names work during the cutover.** The service verbs accept the old name, and
  `update.ps1` looks for the old exe where the new one is absent, so a machine mid-cutover
  is not a machine nobody can update. That compatibility is removed in a later ticket, once
  every install has been through it, and this ticket says so rather than leaving it.
- `iis.json` is not rewritten by this ticket - it is `install-iis.ps1`'s record, and the
  cutover re-runs that script rather than editing its output.
- The runbook covers: stop, back up the database at its **configured** path
  (`Resolve-DbPath`), re-run `install-iis.ps1` with the new names, verify `/version` and the
  banner, and the rollback - which is re-running it with the old ones.

## Verification

`tools/cascade-audit.py` (every path the docs name), both gate scripts, and the runbook
walked against a staged install from `dev-run.ps1` before it is walked against the real one.

## Not in this ticket

`AssetManager_Setup.exe`, which is the installer for all four apps and is not the Asset
Server. Renaming it is a separate argument about what the product is called.
