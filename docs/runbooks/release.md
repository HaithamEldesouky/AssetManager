# Cutting and pushing a release

## Build & Deploy

```
.\tools\package.ps1
```

Run `tools\vendor.ps1 -Role server` and `-Role client` first — one vendored
`lib\` per role, and neither is rebuilt on every package.

`-Component server` or `-Component client` produces one half alone; the default
produces both. It selects what gets **produced**, not which exes get compiled,
and each half is checked only against its own inputs — a server release is
never stopped by a missing `lib-client\`, which is what the old `-Component` did.

Outputs to `dist\<version>\` and nowhere else — one directory per version, and that
directory is the unit that gets carried to a machine:
- `AssetManager-<version>.zip`  ← the server, and what `update.ps1` installs
- `AssetManager_Setup.exe`  ← give this to engineers; it carries a **source** payload
- `NotifierApp-<version>.zip` and `StorekeeperApp-<version>.zip`  ← what a client
  updates *itself* from, served by `GET /download/client/<key>` out of `dist\` beside
  the installed server

The two client zips are written by the same `package.ps1` run rather than by a step
afterwards (#190). They were `bundle-client.ps1`'s to produce on their own and the
runbook asked for it **after** the copy to the machine, which is the wrong order by
construction — they were built on the build machine after the directory they belong in
had already been carried over — and the step that is separate is the step that gets
skipped. A release directory holding the setup exe and not these two is a server that
answers `/version` with its own `latest` and an empty `client_packages`, tells every
installation it is behind and offers it nothing but the browser.

No app exe is built at all. `AssetServer.exe`, `StorekeeperApp.exe` and
`NotifierApp.exe` are gone — PyInstaller compiles the installer and nothing
else (rule 12, rule 14). `output\` and `packages\` are not written, and the
PyInstaller workpath is in `%TEMP%` rather than a `build\` in the repo.
**`ssl_key.pem` is not copied here**: this directory is handed to whoever is
installing, and the key is the one file that must never travel — it stays on
the server, where `install-iis.ps1 -SelfSigned` put it. **No certificate goes
into `AssetManager_Setup.exe` either** — a client with none confirms the
server's fingerprint on first contact (ADR-0010); to supply one quietly, drop a
copy of `ssl_cert.pem` next to the installer, which is the one place
`installer.py` looks: `_ssl_cert_source()` carried a second, the copy baked
into the exe at build time, and #155 removed it - nothing had written one
since 061, and a fallback with no source is what let `_report_unreachable`
ask the same question a different way and be right by accident.

One-time firewall rule on `asset-server`, for the port the server is actually configured to serve on — `8081` unless the Server install was given another, and the installer prints this same line for whichever port it wrote:
```
netsh advfirewall firewall add rule name="Asset Manager" dir=in action=allow protocol=TCP localport=8081
```

`asset_lookup.xlsx` is embedded in `server.py` — no separate file needs to ship.

## Pushing an update (v1.6.0+)

1. Make the change and bump `APP_VERSION` in all four sources — `server.py`,
   `storekeeper_app.py`, `notifier_app.py` and `installer.py` — then commit.
2. `.\tools\vendor.ps1 -Role server`, `.\tools\vendor.ps1 -Role client`, then
   `.\tools\package.ps1`.
3. **The upgrade drill.** `py -3.12 tools\gate.py --all` runs
   `tools\upgrade-drill.py` beside the other gates: it packages the previous release
   and this one, upgrades a seeded install, downgrades it, and updates and rolls back a
   client, failing on any row or file that does not survive. `docs/reference/tooling.md`
   has the six steps. **To package an older version, check out its commit and run its own
   `tools\package.ps1`** - this tree's names modules an older tree does not have, which is
   what the drill does in a temporary worktree.
4. **The engineer-laptop proof (rule 14).** Install `dist\<version>\`'s
   `AssetManager_Setup.exe` on a real engineer laptop - not this machine - and run the
   source-mode client it installs against the server until it has checked in and drawn
   its window. Nothing below is done until that has happened: there is no exe path left
   to fall back to if a laptop refuses the build. `docs/runbooks/source-mode.md` is the
   install on the laptop's side.
5. Copy `dist\<version>\` into `<InstallDir>\dist\` on the target machine — the whole
   directory, which is what that unit exists for — and run
   `<InstallDir>\tools\update.ps1 -Version <version>`. That updater is the one the last
   release installed there, so it needs no `deploy.json` and no `-TargetDir`: an
   unanswered `-TargetDir` falls back to the install the updater is standing in.
6. Drop the new `AssetManager_Setup.exe` next to the server's own files so
   `GET /download/installer` can serve it. The two client zips need no step of their
   own: `package.ps1` writes them into `dist\<version>\` (#190), so step 5's copy of
   that directory is what `GET /download/client/<key>` serves from.

`bundle-client.ps1` writes the engineer-facing zips beside that, for a client installed
without running `AssetManager_Setup.exe` at all; `docs/runbooks/source-mode.md` is the
runbook for both halves. There is no exe channel left to choose between (rule 14).

Back to [CLAUDE.md](../../CLAUDE.md).
