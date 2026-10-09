# Runbook: running the apps from source instead of `.exe`

Source mode ships the Python sources plus a vendored `lib\` and lets a normal,
signed `python.exe` / `pythonw.exe` run them. What Windows executes is then a
binary signed by the Python Software Foundation, not an unsigned PyInstaller
build of ours.

**Why:** our exes have no reputation by construction — each release is a new,
unique, unsigned binary — and Windows Defender ASR already blocks one of them on
at least one machine.

**Status: this is the ship path.** 061 retired `AssetServer.exe`,
`StorekeeperApp.exe` and `NotifierApp.exe`; `tools/package.ps1` builds the
server's source zip and `AssetManager_Setup.exe`, which itself carries a source
payload. There is no exe path left to fall back to. **Source mode has still not
run on a real engineer laptop and IT has not answered** — that proof was the
condition on retiring anything and is now the gate on releasing this build at
all. Read [What is not proven yet](#what-is-not-proven-yet) before deploying
this to anyone.

---

## What source mode requires

Python **3.12** on the machine, from python.org or `winget install
Python.Python.3.12`.

The version is not incidental. `lib\` contains compiled extensions (`pillow`,
`charset_normalizer`) built for one Python minor version, so a bundle vendored
under 3.12 does not run under 3.11. `vendor.ps1` stamps `lib\PYVER` and
`applaunch.py` refuses to start when it disagrees, naming the version needed —
otherwise the failure is an `ImportError` deep in a library, invisible under
`pythonw.exe`, and the engineer has nothing to report.

---

## The pieces

| file | role |
|---|---|
| `applaunch.py` | Puts `lib\` on `sys.path` and runs the app. Every foreseeable startup failure ends in a message box and a line in `launch.err.log`, because `pythonw.exe` has no console and an unhandled `ImportError` is otherwise completely silent. |
| `run_server.py` | Server entry point. Plain `.py`: it has verbs (`serve`, `migrate`) and IIS and `migrate.ps1` both read its output, which `pythonw.exe` discards. |
| `run_storekeeper.pyw`, `run_notifier.pyw` | Client entry points. `.pyw` so no console window sits behind the GUI. |
| `run_installer.pyw` | Entry point for `installer.py` inside a client bundle. |
| `client_update.py` | What applies the *next* bundle, without an installer and without an engineer. Phase one runs inside the app: it reads the zip out of `GET /version`'s `client_packages`, downloads it over the pinned session and checks size, SHA-256 and manifest - this app, this version, this Python minor (rule 13) - before anything is stopped. Phase two is a second process the app spawns before quitting: it waits on the app's pid, saves what it will overwrite into `update_rollback\`, extracts, restarts through the launcher the manifest names, and restores if the app does not come back. Writes `update.log`. |
| `requirements-server.txt`, `requirements-client.txt` | Pinned dependencies per role. Pinned so two packages built from one commit are identical, and because the build machine may not always have a route to PyPI. |
| `tools/vendor.ps1` | `pip install --target` into `lib-<role>\`, then strips every `.exe` pip left behind and stamps `lib\PYVER`. `package.ps1` runs it itself (with `-Clean`) for a role whose lib is absent or unstamped, so the explicit runs below are the deliberate form rather than a precondition to remember; a lib that is there and stamped is never re-vendored. |
| `tools/bundle-client.ps1` | The one implementation of staging a client's source payload. With no `-App` it writes the engineer-facing zip for both - `dist\<v>\NotifierApp-<v>.zip` and `dist\<v>\StorekeeperApp-<v>.zip`, one app's payload each - and `-App notifier|storekeeper` writes one of them alone. `-StageTo <dir>` puts the same payload, both apps, where `package.ps1` can hand it to PyInstaller. |
| `tools/package.ps1` | Builds the release: `dist\<v>\AssetManager-<v>.zip` for the server and `dist\<v>\AssetManager_Setup.exe` for the clients, or either alone with `-Component server` / `-Component client`. Vendors a missing lib for whichever roles that selects, and for no others. |

`installer.py` serves both modes. It decides which by looking at what sits
beside it (`_payload_mode`) rather than taking a flag, so it cannot be told to
install files that were never shipped.

---

## Deploying a client (Storekeeper or Notifier)

On the build machine:

```bash
.\tools\vendor.ps1 -Role client -Clean
```

```bash
.\tools\bundle-client.ps1
```

That writes both zips, which is what a release wants. `-App notifier` or
`-App storekeeper` writes one alone.

One `vendor.ps1 -Role client` run serves both bundles — the dependency list is
the same for either app, and re-running pip per bundle would only be slower.
Each bundle carries only its own app source, so a Storekeeper bundle contains no
`notifier_app.py` and vice versa.

**No bundle carries `ssl_cert.pem` any more.** 061 removed `-CertPath` from this
script rather than leaving it to be carried unused: a fresh install offers the
server's SHA-256 fingerprint for confirmation on its first `https://` call and
pins it if the engineer accepts (ADR-0010). To spare somebody reading a
fingerprint off the Server GUI, copy the certificate `install-iis.ps1` wrote to
`<InstallDir>\ssl_cert.pem` next to the unzipped bundle (or next to
`AssetManager_Setup.exe`) before running the installer — `installer.py` looks
there and supplies it quietly.

Then on the engineer's laptop:

1. Install Python 3.12 if it is not there.
2. Unzip the bundle somewhere permanent.
3. Run `run_installer.pyw` — the same installer UI as before, including the live
   admin-password check.

The installer copies the payload to the chosen directory, writes `config.json`,
and creates a Desktop shortcut whose target is `pythonw.exe` and whose argument
is the launcher. Its working directory is the install directory, because every
app resolves `config.json` and `ssl_cert.pem` relative to itself.

### Updating a client afterwards

Only the first install needs the bundle carried to the laptop. After that,
leave both zips where the server can serve them:

```bash
copy dist\<v>\NotifierApp-<v>.zip      <InstallDir>\dist\<v>\
copy dist\<v>\StorekeeperApp-<v>.zip   <InstallDir>\dist\<v>\
```

`GET /version` then advertises each zip it can actually see, and each client
offers to apply its own on the next launch or from its Check for Updates
control. `<InstallDir>\dist\` is the same directory `update.ps1` reads the
server's own releases from since 062, and the server looks in `<dist>\<version>\`
first and then `<dist>` itself, the same two shapes for the same reason.

The zip is resolved only at the **published** version, so a client asks for
what `/version` told it about and a bundle left behind by an older release is
not handed out. A server with no bundles beside it is not a broken one: every
client falls back to the browser download of `AssetManager_Setup.exe`, which is
also what a client built before `client_packages` existed does.

Nothing of ours is an executable on this path (rule 12) - a zip of `.py` files,
the launchers and the vendored `lib\`, restarted through the same signed
`pythonw.exe`. If an update fails, `update.log` next to the app is what to
ask for, and `update_rollback\` beside it holds the outgoing files until the
next update replaces it.

---

Measured on the build machine: **7.9 MB** zipped for the Notifier (488 files),
against **43.6 MB** for `AssetManager_Setup.exe`, which carries both client apps
and a Python runtime in one file. There is no `NotifierApp.exe` to compare
against any more.

---

## Deploying the server

Source mode does not change where the server runs. It is hosted by IIS via
HttpPlatformHandler exactly as in [ADR-0001](../adr/0001-host-api-on-iis-via-httpplatformhandler.md);
the only difference is that `web.config`'s `processPath` is `python.exe` with
`run_server.py serve` as its argument instead of `AssetServer.exe serve`.

```bash
.\tools\vendor.ps1 -Role server -Clean
```

```bash
.\tools\package.ps1 -Component server -CertPath C:\AssetManager\ssl_cert.pem
```

Copy the whole of `dist\<v>\` to the server as `C:\AssetManager\dist\<v>\`, then:

```bash
.\tools\update.ps1 -Version <v>
```

That updater is `C:\AssetManager\tools\update.ps1`, which the previous release
installed: it needs no `deploy.json` and no `-TargetDir`, taking the install
directory from its own location, and `dist\` under that directory is the one
place it reads a package from. Pass `-BaseUrl` for the health check and the
auto-rollback. On the **first** source install there is none there yet — it
ships inside the package and is put there by the install that applies it — so
carry `tools\` to the server by hand that once and name the zip outright.
`-Version` and `-Package` are separate parameter sets, each mandatory in its
own, so passing both fails with "Parameter set cannot be resolved using the
specified named parameters": it is `-Package` alone.

```bash
.\tools\update.ps1 -Package .\AssetManager-<v>.zip -TargetDir C:\AssetManager
```

```bash
.\tools\install-iis.ps1 -PythonExe "C:\Program Files\Python312\python.exe"
```

On an interactive run that command asks for the install directory, port, site
name and pool name, each offered with the value it resolved as the default --
`-PythonExe` is not one of the four and is never asked about. Press Enter through
them, or pass any of them on the command line to settle it in advance.

`install-iis.ps1` detects which kind of install `InstallDir` holds and points
`web.config` accordingly. Set `pythonExe` in `deploy.json` rather than relying on
`python` resolving: the IIS app pool identity has its own environment, and a
`PATH` lookup that works in your shell may not work there. The full resolved
path is what goes into `web.config`.

`update.ps1` and `migrate.ps1` both find the migration engine themselves
(`Resolve-ServerRunner` in `_deploy.ps1`): `AssetServer.exe migrate` if the exe
is present, otherwise `python run_server.py migrate`. The engine stays in
`server.py` in both modes — PowerShell has no SQLite provider.

That interpreter is **resolved through `Get-Command` inside that helper**, so
what both scripts invoke is a full path. `$ErrorActionPreference` is `Stop` in
each of them, so a bare `python` that is not on the PATH of the account running
the update raises PowerShell's own `CommandNotFoundException` at the call — in
`update.ps1` that call is reached *after* the app pool has been stopped and the
database copied aside, which is a server down with no rollback. With nothing to
resolve, they refuse instead and name `pythonExe` — set it in `deploy.json`, or
pass `-PythonExe`, on any machine where `python` is not on that account's PATH.
A server whose `deploy.json` was never written by hand has neither, which is the
usual case since no `deploy.json` ships in a package.

### The Windows Service does not work in source mode

`vendor.ps1` strips `win32\pythonservice.exe` out of `lib\`, because it is an
unsigned executable and shipping it would put back exactly what source mode
removes. Without it the `install`/`start`/`stop`/`remove` verbs cannot work from
a vendored `lib\`.

This costs nothing under IIS, which uses `serve` and never touches the service
layer. `server.py` already degrades cleanly, guarding the import behind
`HAS_WIN32SVC` and printing a clear message for a service verb it cannot honour.
A source install that genuinely needs the service must have `pywin32` installed
into the interpreter instead, so its postinstall step runs.

---

## Mixing modes

Nothing builds an exe package now, but a machine can still be holding one built
before 061. The source zip no longer carries a `-source` suffix - it is
`AssetManager-<v>.zip`, the name an exe package wears too - which is safe because
no version number is shared between the two eras, 061 predating every version
since. `update.ps1 -Version` resolves that name and the suffixed one a release
before this change wrote, and refuses when both exist rather than guessing.

Installing one kind over the other leaves both sets of files in the directory.
`update.ps1` warns and tells you to re-run `install-iis.ps1`; it does not block,
because deliberately migrating between modes is a real thing to want. Delete the
exes only once the source install is verified — they are the rollback.

---

## When an app will not start

Look for `launch.err.log` next to the launcher. `applaunch.py` writes there for
every startup failure it can foresee, and it also catches an exception thrown
after the app has started and records the traceback.

| message | cause |
|---|---|
| Wrong Python version | `lib\PYVER` disagrees with the running interpreter. Install the version named, or re-vendor for the one present. |
| Installation is incomplete | `lib\` or the app file is missing. Re-run the installer. |
| Python is too old | Below 3.10. |
| The app stopped unexpectedly | The app started and then failed; the traceback is in the log. |

No `launch.err.log` and no window means the process is running but doing nothing
visible — for the Notifier that is normal, since it lives in the system tray.

---

## What is not proven yet

Verified on this build machine (`CLIENT-LT-11220`, Python 3.12, Windows 11
Enterprise 26200):

- The Notifier runs from source under `pythonw.exe`, polls `/pending` within
  1.2–4.1s of launch, and stays up. The process image is `pythonw.exe`, whose
  Authenticode signature is `Valid` (Python Software Foundation).
- The Storekeeper runs from source under `pythonw.exe`: its window opens
  (`Asset Manager — Storekeeper (v2.3.0)`), and the server logs the `/members`,
  `/asset_types` and `/export` calls it makes on startup. Its 487-file bundle
  verifies against the manifest, installs through `installer.py`'s own
  `_deploy_component`, and puts no `.exe` on disk. `openpyxl` loads from the
  installed `lib\` rather than the machine's Python and round-trips a styled
  workbook — the Excel export is driven rather than assumed, because it is the
  one dependency the Storekeeper uses and the Notifier does not, and a missing
  transitive would otherwise surface the first time a user clicks Export.
- The server runs from source: `run_server.py serve` answers `/health`,
  `/version` and `/members`, and creates `assets.db`.
- Neither installed directory contains a single `.exe`.
- `update.ps1` installs a 1175-file source package with all hashes verified;
  `migrate.ps1` drives v0→v2→v1→v2 with a backup each time and no exe present.
  That run predates 062, which put `tools\update.ps1` and `tools\_deploy.ps1`
  into the payload, so a package built now carries two files more than the
  number recorded here. The count is left as it was measured rather than
  adjusted by arithmetic — it is the record of a run, not a claim about the
  current build.
- `applaunch.py` refuses a `lib\` built for another Python and names the version
  needed, and refuses a missing `lib\`.
- 063's applier, driven four ways against a **stand-in app** - a `.py` file that
  sleeps, standing in for a Notifier - in a scratch install directory. A clean
  update replaced the app file and the whole of `lib\`, left a file no manifest
  names untouched, put the outgoing copies in `update_rollback\1.0.0\` and
  removed the staging directory, returning 0 after 14.2s (2s waiting for the
  app to go, 12s of health check). A new build that **exits** and one that
  **stays alive and writes `launch.err.log`** - which is what `applaunch.py`
  actually does, since its refusals end in a message box - were each caught,
  rolled back and the old build restarted, `update.log` naming which of the two
  signals fired. An app that never exits was refused after the full 60s with
  nothing written and no rollback directory created.

**Not verified:**

- **Any machine other than this one.** In particular no engineer laptop, where
  the ASR policy assignment may differ. This was the gate on retiring the exes;
  061 retired them, so it is now the gate on releasing at all — there is no exe
  path left to fall back to if a laptop refuses a source-mode client.
- **The updater replacing itself.** 062 ships `update.ps1` inside the package
  and installs it to `<InstallDir>\tools\`, so applying a release overwrites the
  script that is applying it. The argument that this is safe is sound —
  PowerShell parses a script whole before running a line of it, `_deploy.ps1`
  is dot-sourced before anything is written, and the outgoing copy goes into
  `rollback\<old-version>\` with the rest — but no run on a real install has
  demonstrated it, including the auto-rollback leg that restores the updater
  along with the build.
- **A real client updating itself.** 063's two-process handover was driven on
  this machine against a **stand-in app** (see "Verified" above), not against
  an installed Notifier. What that leaves open is the part a stand-in cannot
  stage: a `lib\` of real `.pyd` files being deleted and rewritten under a
  process that had them loaded a moment earlier, and a Tk app leaving through
  its own quit path rather than a `time.sleep` ending. Both are the reason
  the applier waits on the pid at all, and neither has been watched happen.
- **IIS hosting a source install.** `install-iis.ps1` needs elevation, so only
  its runner-detection block was exercised here (lifted verbatim out of the
  script). The `web.config` it writes has not been served. Do this during the
  cutover in [iis-cutover.md](iis-cutover.md).
- **Whether ASR is quiet about source mode over time.** The phase-1 spike
  recorded no Defender or ASR event, but `lib\` legitimately contains 10 (client)
  and 59 (server) `.pyd` files — unsigned DLLs, not executables. Nothing flagged
  them, and the rules that fired on our exes are about executables, but this has
  only days of observation behind it.
- **Autostart.** Still deliberately absent. Whether a shortcut to a signed
  `pythonw.exe` avoids the Run-key and Startup-folder heuristics that the
  unsigned exe tripped is untested.
