# Release tooling

## Release Tooling (`tools/`)

`tools/package.ps1` produces a release into `dist\<version>\` — the server's source zip and `AssetManager_Setup.exe`, or either alone. These scripts turn a build into something installable and reversible.

### `tools/package.ps1`

Builds a release into `dist\<version>\`, one directory per version: the server as
`AssetManager-<version>.zip` and the clients as `AssetManager_Setup.exe` carrying
a **source** payload. `-Component server` or `-Component client` produces one alone; the
default produces both.

The server zip holds `server.py`, `server_gui.py`, `server_cert.py`,
`register_assets.py`, `register_transactions.py`,
`register_engineers.py`, `server_mail.py`, `server_sync.py`,
`server_clients.py`, `server_log.py`, `server_archive.py`,
`server_lookup.py`, `ui_kit.py`,
`run_server.py`, `applaunch.py`, the vendored
`lib-server\` as `lib\`, the migrations and a
`manifest.json` (version, schema version, commit, SHA-256 per file, `mode` and
`python_version`), **and the updater itself** — `tools\update.ps1` with the
`_deploy.ps1` it dot-sources, installed to `<InstallDir>\tools\`. Shipping the
updater inside the release is not circular: it is never needed to *obtain* a
package, only to apply one, and by then the install before
this one has already put it on the machine. What it buys is that the updater on a server
is always the one that shipped with the newest build installed there, rather than
whatever copy somebody last carried over. Nothing else from `tools\` travels:
`install-iis.ps1` is run once by hand from a copied directory, and `migrate.ps1` wraps a
verb `server.py` already carries. **The zip has dropped its `-source` suffix**: that
suffix existed to tell this package from an exe one, nothing has built an exe package
since 061 (rule 14), and no version number is shared between the two eras, so there was
nothing left for it to be distinguished from. `update.ps1` still resolves the suffixed
name beside the bare one - a machine can be holding a package written before this, and a
pre-061 exe package wears the bare name itself - and still refuses when both exist for one
version rather than guessing between them.

The installer's payload is staged by `bundle-client.ps1 -StageTo`, never by a second copy
of that list here: **there is exactly one implementation of "stage a client's source"
payload**, so the zip that script writes on its own and the payload PyInstaller embeds are
the same files by construction. **PyInstaller is used for one thing only:
`AssetManager_Setup.exe`.** No app exe is built at any point.

**And the client half runs that same script in its other shape as well**, with no `-App`,
which writes both update zips into the `dist\<version>\` this run is already writing
(#190). That is what makes this one list rather than a second copy of it. After the exe
rather than before, so a PyInstaller failure is not paid for after two zips have been
built, and **both files are checked by name** rather than trusted to `$LASTEXITCODE`, for
the reason the staged payload above is: a `.ps1` that returns without calling `exit`
leaves that variable at whatever the last native command set, and what is being asserted
is the file sitting under the name `server.py` resolves it by. `cascade-audit.py` holds
this script to invoking `bundle-client.ps1` in **both** shapes — the only gate that can
see a release directory's contents at all, the rest of that being observable only by
running a build.

**Both halves are checked before either is produced, and each only against its own
inputs.** A server release that stopped because `lib-client\` had not been vendored is
the defect the up-front `Checking prerequisites` step exists to prevent — `-Component
server` never looks at `lib-client\`, `-Component client` never looks at `lib-server\`,
and neither can fail on the other's inputs. Each asks `Get-VendoredPyVer` in
`_deploy.ps1`, so a missing or unstamped lib names `vendor.ps1 -Role <role>` for the role
actually missing rather than for whichever one the script happened to reach first.

**And an absent or unstamped lib is vendored rather than named.** That step already
resolved which role was missing and already printed the command to run; running it is
what was left, so a first build on a fresh checkout is one command instead of a refusal
quoting the next one. It is `Ensure-Vendored`, called for exactly the roles `-Component`
selects, so `-Component server` still never vendors the client and still never fails on
it. A lib that is there and carries its `PYVER` is **left exactly alone**: vendoring is
still not folded into packaging, for the reason `bundle-client.ps1` gives - one vendored
lib serves both client bundles and pip is slow - and there is still no staleness check
here to decide a present one has gone out of date, so an ordinary release run costs what
it always cost. `-Clean`, because the state this repairs other than an absent directory
is the half-written one an interrupted pip run leaves, which installing over the top of
would keep. **A stray `.exe` deliberately keeps its refusal**, though `vendor.ps1` would
strip it: a lib that has grown an executable is a directory something other than
`vendor.ps1` wrote into, and rule 12's refusal is a thing to be read rather than a build
step to be re-run past - `Get-VendoredPyVer` still makes that one, on the line after.

**Refuses a dirty working tree** — the manifest's commit is the only record of what went
into the payload — and refuses if the four `APP_VERSION` values disagree. **Nothing
untracked goes into the payload either**: `config.json` was staged as an `$Extras`
file until #108, and an ignored file is exactly what `git status --porcelain` does
not report — so the refusal above could not see it, the manifest hashed a per-machine
*client* file beside `server.py`, and two machines building one version produced two
different packages stamped with the same commit. `update.ps1` writes every name a
manifest carries, so each update then wrote that file, `client_id` and all, into an
install directory over a name the server has never read. There is no `$Extras` list
any more: what a package is assembled from is what git tracks, and `cascade-audit.py`
holds both release scripts to it. `-AllowDirty`
is for local testing and stamps the package unreleasable; it is deliberately **not**
settable from `deploy.json`, since a forgotten line in a config would quietly make every
package unreleasable. **There is no staleness check and no `-Force`**: that pair existed
because an exe can lag the source it was compiled from, and a payload of `.py` files
contains the very files the version was read from, while the one exe left is rebuilt on
every run.

`-DistDir` (or `distDir` in `deploy.json`) moves the ship root and the `<version>` under
it is not negotiable; `-ServerLibDir` and `-ClientLibDir` (`serverLibDir`,
`clientLibDir`) point at the two vendored libs, which are two directories now rather than
one. A `deploy.json` still carrying the `outputDir`, `packageDir` or `libDir` these
replaced is **warned about by name**, since a key nothing reads is a build writing
somewhere other than where the file says.

**Most of the certificate machinery is gone.** `AssetManager_Setup.exe` carries **no**
`ssl_cert.pem` at all: a client given none confirms the server's fingerprint on first
contact (ADR-0010), and an install that should not have to ask takes a copy dropped
beside the installer, which is where `installer.py` looks first anyway. The server
package still ships one, **best effort** — `-CertPath` / `certPath` (default
`<Root>\ssl_cert.pem`), else `<installDir>\ssl_cert.pem` from `deploy.json`, else `GET
<baseUrl>/cert` from the live server, whose SHA-256 fingerprint is **printed** because
verification has to be relaxed for that one GET (a self-signed server cannot be verified
before its certificate is in hand; no credential crosses it, and the human at the console
is what checks it). Where none of the three answers it **warns and packages anyway**
rather than failing: the file it would have carried is the server's own and the server is
where it already is. **`-NoCert` and `-SelfSigned` are gone** with the failure they
existed to answer — a build machine minting a key for a server it cannot bind it on was
the sharpest tool here, and a package whose key never arrived stranded every client that
had pinned the certificate; `install-iis.ps1 -SelfSigned` generates and binds in one run
on the server, where the key never leaves. `-CertPath` stays. **Refuses** a certificate
containing a `PRIVATE KEY` — fetched bytes included — and any staged file named like a
key: the build copies no key anywhere, and a key sitting beside a build is exactly the
file that check is for.

**Stamps the installer with the app icon**, drawn into the PyInstaller workpath by
`_devtools.py icon` at the start of the run and never committed: the artwork is
`ui_kit.app_icon`'s, the same one the windows and the trays draw, so the exe's icon and
the running app's cannot differ. A build that cannot draw it fails rather than stamping
PyInstaller's own.

### `tools/update.ps1`

Installs a specific version onto a machine — upgrade or downgrade. `-Version 2.0.0
-TargetDir C:\AssetManager`, or just `-Version 2.0.0` with `installDir` and `baseUrl`
in `deploy.json` -- **or with neither**, since a `-TargetDir` nothing answered falls
back to the install this script is standing in: the package puts it in
`<InstallDir>\tools\`, no `deploy.json` ships in any package, and a server that
never had one written by hand therefore failed at the first step of the very update
every runbook here spells `-Version` and nothing else. It is
`Resolve-InstallFromTools` in `_deploy.ps1` rather than three lines here, so a gate
can drive it (`deploy-checks.ps1`). Guarded twice, a checkout
having a `tools\` of its own -- an install marker beside it (`installed.json`, this
script's own record, else `server_config.json`, a never-updated install having no
state file) and no `.git` there, since a checkout that has ever run the server
carries a `server_config.json` in its root. The run says where the directory came
from. What `deploy.json` still buys is `baseUrl`, which is never derived from
`port`: guessing the scheme wrong fails the health check and rolls back a good
update. **It ships inside the server
package and is installed to `<InstallDir>\tools\`**, with `_deploy.ps1` beside it, so the
updater on a machine is always the one that shipped with the newest build installed
there. **It replaces itself as it runs** and that is safe rather than lucky: PowerShell
parses a script whole before executing a line of it, `_deploy.ps1` is dot-sourced long
before anything is written, and the outgoing copy goes into `rollback\<old-version>\`
with every other replaced file, so a health-check failure restores the updater along
with the build. **Where it reads a package from is one place: `dist\` under the install
directory** — `-PackageDir` names somewhere else for a one-off and is then the only
place looked, since falling through to a directory the caller did not name would
install a package they never pointed at. **Pointed at a file rather than a
directory it is the package itself** and is read as `-Package`: a zip's own path
is what somebody carrying a release actually has in hand, and the two readings
cannot both hold, a leaf never being a directory -- so what the other reading did
with one was look in `<zip>\<version>\` and `<zip>\`, two directories that cannot
exist, and refuse naming the file it had been handed as somewhere it could not
look. The version is the manifest's from there on, as it is on every run, so a
package whose name spells the version differently is installed as itself rather
than refused over a name it was never asked about. **That directory is
looked at twice**, `<dir>\<version>\` first and then `<dir>` itself: `package.ps1` writes
`dist\<version>\` and that whole directory is what gets carried to a machine, while a zip
carried on its own lands beside it rather than in a subdirectory, so both shapes
are looked for and the line printed says which answered. The four-place search this
replaced — the working directory, then `distDir` in `deploy.json`, then the repo's
`dist\` — existed for an updater carried to a machine by hand, and every one of those
places was a guess about where the person carrying it had been standing; an updater that
arrives with the release has nothing left to guess between. A `deploy.json` still setting
`packageDir` or `distDir` is **warned about by name**, because a server that has been
updating out of `distDir` would otherwise start reading from somewhere else in silence,
which is the one thing the printed line exists to prevent — and the warning says that
`distDir` is still `package.ps1`'s ship root on a build machine rather than calling the
key a mistake. When neither shape holds the version, it lists each place it looked
and what was there and **asks for a directory** rather than failing — but only where
somebody can answer (`Test-CanPrompt` in `_deploy.ps1`: `UserInteractive` alone is not
enough, since a scheduled task under a logged-on user reports true with no console, and
nothing is asked under `-WhatIf` either). An empty answer, or nobody to ask, keeps the
refusal it always had. Both packages still resolve and both in one directory is still a
refusal, not a re-ask and not a reason to try the next one: that is an ambiguity, and
another directory is not the answer to it. Verifies manifest hashes, stops the IIS app
pool or the service - **which of the two that is gets resolved before anything is stopped
or written, and asked about rather than guessed**: `iis.json` in the install directory is
the record `install-iis.ps1` left of what it bound, and where it is missing, or names a
site IIS no longer has, an interactive run lists the sites IIS does have and asks which
one serves this install, reading the pool off the site rather than trusting a stale name;
an empty answer names the `AssetManagerServer` service. Where there is nobody to ask -
`Test-CanPrompt` again, so nothing is asked under `-WhatIf` - the behaviour it always had
stands, and either way the line it prints names the host it decided on and where that came
from. An install whose `iis.json` had gone missing used to be handed to `sc.exe`, which
stops nothing on an IIS host: the files were then written under a running worker and the
health check read the old version back. Nothing here writes `iis.json` - that file is
`install-iis.ps1`'s record, not an answer typed at one update, and the prompt says so.
Then **copies the database itself** — at the install's configured `db_path` (via
`Resolve-DbPath`, not `assets.db` beside the exe — against a moved install the old code
created an empty database, migrated that, and reported success), with its `-wal` and
`-shm` files, into `rollback/<old-version>/` — and only then migrates it. That copy is
this script's, not the migration's: `server.py migrate` writes its `.bak-v*` only when it
has work to do and returns early when the schema is already at target, so an update that
changes no schema used to back up nothing while overwriting every exe under it. It is
taken **after** the host is stopped - waited for rather than slept through, since
`Stop-WebAppPool` and `sc.exe stop` both return before the worker has gone - because a
live SQLite file copies as a half-written page and its `-wal` is a second file that has to
agree with the first, and still before anything on disk is written. Then it moves `lib\`
into `rollback/<old-version>/` **whole** and writes the package's into the empty directory
that leaves - the same wholesale replacement `installer.py` and `client_update.py` make,
for the same reason. Writing that tree file by file removes nothing, so a renamed or split
module, a dropped submodule or the `<pkg>-<version>.dist-info` every bump renames survived
from the old pin set and went on being found by `applaunch`'s `sys.path` entry beside the
new one; `PYVER` catches a `lib\` built for the wrong Python (rule 13) and nothing catches
a half-merged one. It is sharpest on the way back, since a file only the incoming `lib\`
carried was never saved, so the rollback that exists to reach a known-good state produced
a tree neither release ever shipped - and a downgrade, which is the moment somebody is
backing out of a build that does not work, did the same thing without failing at all.
Moved rather than copied for the reason `client_update.py` gives, several hundred copies
being a great deal of churn for a directory that has to go back as one thing anyway;
`lib/*` is then kept out of the per-file save and the per-file restore, or half of each
tree goes back over the other; and a second run of the same update **keeps** the `lib\`
already in `rollback\` rather than overwriting it, the way the database copy beside it is
kept - a failed health check leaves the installed version where it was, so the rerun
resolves that same directory. `cascade-audit.py` holds all three appliers to it. Then it
saves **every other file the package will overwrite** to that same directory (not just the
exes — a
package can carry `ssl_cert.pem`, and restoring old exes next to a new certificate is a
rollback that still strands every client) — **and `installed.json` with them**, which no
manifest can name, being this script's own record of which build is on the machine. It
was the one file an update overwrote and never put back, so a rollback left the old
build running beside a state file naming the version that had just been rolled back;
since both `rollback\<version>\` and the upgrade-or-downgrade direction are resolved
from that file, the next attempt looked in a directory that did not exist, the guard
keeping the pre-migration database copy could not fire, and the database already
migrated forward by the failed run was copied in as that run's “before” copy — over the
top of the one file the failure message sends somebody to restore (#111). It goes in
the same list the restore reads, rather than beside it, because one list is what stops
the two halves disagreeing about what was replaced. Then it writes the new ones and
starts the host — `Start-WebAppPool` under IIS, `sc.exe start` for the service —
and **a start that does not come up is a `Warn` naming what went wrong, not a `Fail`
that rolls back**: the files and the database are already correct, and the rollback
below exists for a build that does not serve, which is not yet known at this point. A
`sc.exe start` exit other than 0 or 1056 (already running) is warned by code; an
app pool throwing from `Start-WebAppPool` is warned by its exception message. With
`-SkipHealth` or no `-BaseUrl` the run still ends there — the line that would read
`[OK] ... complete (unverified)` reads instead that the host did not start, so a
console watching for `[OK]` cannot mistake this run for one. With a `-BaseUrl` given,
the health check below is what actually finds this out for the case that reads it —
the `/version` poll never answers a host that never started, so the run still falls
into the same rollback the check always had. Then it health-checks `/version` and
**restores those files automatically if it fails — never the
database**: the new build has been serving for as long as the check took, every
transaction recorded in that time is only in the live file, and putting an older copy back
would destroy them. **That check goes through `Invoke-PinnedRequest`**, which is the
only way it can pass at all against the certificate this deployment actually has:
a `baseUrl` of `https://asset-server:8081` — the value this script's own help
and both its examples carry — could not be verified from Windows PowerShell 5.1,
so every one of the ten attempts threw, `$ok` stayed false, and a **good update
was rolled back** over a database already migrated forward, which is the one
state the failure message below sends somebody to sort out by hand (#109). It
pins `<InstallDir>\ssl_cert.pem`, the file the clients pin and `GET /cert`
serves, so what this asks of the server is what they will. A server presenting
something else is **named on the way out** — both fingerprints, the installed one
and the served one — because that is a package carrying its own certificate
rather than a bad build, and it is the mismatch warned about below; the rollback
restores the installed file, so the two agree again afterwards. Where that mismatch is
against an **IIS site** rather than a bad build, the health check does not stop at naming
it: it **reconciles**, importing the install directory's own `ssl_cert.pem`/`ssl_key.pem`
into `Cert:\LocalMachine\My` (`Import-CertPair` in `_deploy.ps1`, skipped when a
certificate with that thumbprint is already there with its key) and rebinding the site to
match (`Set-SiteCertificate`) — `ssl_cert.pem` is the source of truth, being what `GET
/cert` serves and what every client has already pinned, so the binding is corrected to it
and never the reverse, which would strand every client that already pinned the file.
**Reconciled after the health check and before the run is called good**: a rebind that
itself fails leaves `$ok` false exactly as any other failed attempt does and falls into the
same rollback below, with no rollback logic of its own to keep in step with that one.
**`-WhatIf` rebinds nothing**: the same local-only comparison (`Get-CertMismatch` in
update.ps1, no network call) runs in the planning step's preview and prints both
fingerprints there instead. Where there is no IIS host at all — the service, or a
standalone install — there is no site to resolve and nothing to reconcile, and this
mismatch warning stands exactly as it did before. The database copy is restored **by hand**, by someone who has looked;
the failure message names it alongside the migration's `.bak-v*`. **Warns when the package's
`ssl_cert.pem` differs from the installed one, naming both fingerprints** — the
installed one and the package's, because the question being asked is which certificate
the clients on this network pinned, and one digest on its own answers nothing. Every
client holding the outgoing one fails closed against the new certificate, the hourly `GET
/cert` refresh included, so each has to be reinstalled or have its `ssl_cert.pem` deleted
for somebody at that machine to confirm the new fingerprint (ADR-0010); the outgoing copy
is named in `rollback\`. The digest is `Get-CertFingerprint` in `_deploy.ps1`, over the
DER bytes, which is the number the Server GUI's Server Settings window and the client's
own prompt both show. Supports `-WhatIf`. Merges the package's
migrations into the installed set rather than replacing it, because a downgrade needs the
newer build's `down()`. Handles **source packages** too: `-Version` resolves either
`AssetManager-<v>.zip`, which is what `package.ps1` writes, or `-source.zip`, which is
what it wrote before the suffix was dropped and what a pre-061 exe package is told apart
from - and refuses when both exist rather than guessing,
migrations run via `Resolve-ServerRunner` — which resolves the interpreter
before this script invokes it, the `&` here sitting after the host has been
stopped and the database copied aside — and it warns when a package's `mode` does not
match what is installed (both file sets then sit in the directory) without blocking —
migrating between modes on purpose is a real thing to want. Every copy goes through
`Copy-Into`, which creates parent directories: `Copy-Item` does not, and a source package
arrives several hundred files deep inside `lib\`.

### `tools/migrate.ps1`

Schema migrations: `-TargetDir <dir>` (or `installDir` in `deploy.json`) alone for status,
`-Target N` to move, plus `-DryRun`. `-DbPath` defaults to the install's **configured**
database via `Resolve-DbPath`, so a status report or a migration lands on the file the
server actually opens. A thin wrapper — the engine lives in `server.py`'s own `migrate`
verb, because PowerShell has no SQLite support (neither 5.1 nor 7 ships a provider, and
`sqlite3.exe` is not on Windows) while `server.py` already imports `sqlite3` and is on
every machine being updated by definition. Reached as `AssetServer.exe migrate` or, on a
source install, `python run_server.py migrate`; `Resolve-ServerRunner` in `_deploy.ps1`
decides which, shared with `update.ps1` because a wrong answer means a migration that
silently does not run — and it hands back a full path, an unresolvable `python`
being refused there by name rather than at the `&` here. State is SQLite's `PRAGMA user_version`, so no bookkeeping table
exists.

### `tools/_deploy.ps1`

Settings resolution shared by `install-iis.ps1`, `update.ps1`, `package.ps1`,
`migrate.ps1` and `bundle-client.ps1`, plus `Resolve-ServerRunner` (exe-vs-source
migration engine — and the **interpreter it answers with is resolved through
`Get-Command` before it is handed back**, so `File` always carries a full path.
That is `vendor.ps1`'s rule one level out: `$ErrorActionPreference` is `Stop` in
both callers, so a bare `python` that is not on PATH raises PowerShell's own
`CommandNotFoundException` at the `&` rather than the refusal written under it —
and in `update.ps1` that `&` is reached *after* the app pool has been stopped and
the database copied aside, so what an unresolvable name cost was a server down
with no rollback and nothing naming `pythonExe`. The name is decided here, so it
is resolved here, and one answer serves both callers; the refusal names
`pythonExe` in `deploy.json` and `-PythonExe`, and a server with no `deploy.json`
written by hand has neither, which is the machine this was found on.
`cascade-audit.py` holds this one by name, the `&` being a file away from the
decision and so invisible to the check it holds every script's own interpreter
variable to), `Resolve-InstallFromTools` (the install directory a `tools\`
directory is part of, or `$null` — `update.ps1` ships inside the package and is
installed to `<InstallDir>\tools\`, so the parent of its own script root says
which install it is applying a release to, and no `deploy.json` ships in any package
for it to be told twice by. Guarded twice, a checkout having a `tools\` of its own:
one of the marker files the caller names has to sit beside it, and no `.git` may,
since a checkout that has ever run the server carries a `server_config.json` in its
root and would answer the first test. Here rather than inline in `update.ps1`, its
only caller, for `Test-FirstTimeCertSetup`'s reason — that script stops an app pool
and overwrites an install, so no gate can run it, while `deploy-checks.ps1` can
dot-source this file and drive every state over the decision. The markers are the
caller's argument so `installed.json` stays written down once, in the script that
writes it), `Resolve-DbPath` (`db_path` from the install's own
`server_config.json`, else `assets.db` beside the server — shared because every caller
backs the database up before touching it) and `Test-CanPrompt` (is there a human at this
console: `UserInteractive` **and** not `IsInputRedirected` **and** not `-WhatIf`, because
a scheduled task under a logged-on user reports the first true with no console and a
`Read-Host` there hangs until something kills it — it takes `$WhatIfPreference` as a
`[bool]` parameter rather than reading the caller's preference variable through dynamic
scoping), `Get-VendoredPyVer` (validates a vendored `lib-<role>\` and returns its
`PYVER`: the directory is there, it carries a stamp, and no `.exe` survived `vendor.ps1`
— shared because `package.ps1` asks it of `lib-server\` and `bundle-client.ps1` of
`lib-client\`, and each failure names `vendor.ps1 -Role <role>` for the role that is
actually missing), `Get-CertFingerprint` (SHA-256 over a PEM certificate's **DER** bytes,
colon-separated uppercase hex — the same value the Server GUI's Server Settings window
shows, the client's first-contact prompt shows (ADR-0010) and
`X509Certificate2.GetCertHashString("SHA256")` returns; **not** `Get-FileHash` and not
`certutil -hashfile`, both of which hash the PEM's own text and give a number that looks
equally plausible and matches none of the four — shared because `package.ps1` prints it
for a certificate it fetched while `update.ps1` and `install-iis.ps1` each name both
sides of a replacement with it, which is one question asked in three places and the
worst kind to let two spellings answer differently. It takes either a **path** or the
**DER bytes**, the second door being `install-iis.ps1`'s: that caller holds a
certificate out of `Cert:\LocalMachine\My` and no file, since the PEM it is warning
about has not been written yet, and the bytes are what this measures either way — so
the two ways in meet on one line rather than being two implementations of a certificate
decision),
`Invoke-PinnedRequest` (an `https` request that accepts **one** certificate — the one
in the PEM it is handed — and nothing else, with default validation where there is
nothing to pin, which is the only way `update.ps1` and `install-iis.ps1` can probe a
server carrying the certificate `-SelfSigned` minted: it is in `Cert:\LocalMachine\My`
and nothing puts a copy in `LocalMachine\Root`, and 5.1 has no
`-SkipCertificateCheck`. **Not rule 1 turned off** — rule 1 is a *client* deciding
whether to trust a server, while these two ask this machine's own certificate for
`/health` and `/version` carrying no credential, and accepting exactly one certificate
is stricter than the chain check, not looser. A **compiled** callback set on the
request, not a scriptblock and not `ServicePointManager`: .NET invokes the callback on
a thread with no runspace, so a scriptblock throws "There is no Runspace available" and
surfaces as "The underlying connection was closed", reading as the server's fault —
the same trap `package.ps1` writes down — and the policy is process-wide where a
request's own callback is not. It **never throws** for a request that failed, both
callers looping over attempts: `StatusCode` 0 with `Error` saying why, and `Presented`
carrying the fingerprint the server actually offered, since a pin refusal and a server
that is not there are different things to be told. Shared because two scripts probe and
a certificate decision is the worst thing here to hold two copies of),
`Get-BoundCertThumbprint` (the thumbprint IIS actually has bound to a site's https port,
read straight out of `IIS:\SslBindings` rather than off `ssl_cert.pem` — local only, so
`update.ps1` can call it under `-WhatIf`; `$null` for a site with no https binding),
`Test-FirstTimeCertSetup` (are all three of *no certificate source given*, *no `ssl_cert.pem` in the install directory* and *nothing bound to the site* true - the one state in which `install-iis.ps1` may mint a certificate nobody asked for. Here rather than inline in that script, which is its only caller, for what it buys rather than for sharing: the script stands up IIS and cannot be run by a gate, this file is the one every script here dot-sources, and so it is the one `deploy-checks.ps1` can dot-source to drive all four states over the decision with `Get-BoundCertThumbprint` stubbed. `$SourceGiven` is a `[bool]` for trap three's reason), `Import-CertPair` (puts an install directory's own `ssl_cert.pem` and `ssl_key.pem` into
`Cert:\LocalMachine\My` as one certificate carrying its private key — skipped when a
certificate with that thumbprint is already there with a key attached, so a reconcile that
retries on every health-check attempt does not reimport it each time; reads the key as
PKCS#8 or PKCS#1, both readable under the .NET Framework 4.7.2 Windows Server 2019
ships, unlike the PFX-round-trip overloads that need 4.8) and `Set-SiteCertificate`
(rebinds a site's https port to a thumbprint, mirroring `install-iis.ps1`'s own
`IIS:\SslBindings` remove-then-recreate — shared because `update.ps1`'s reconcile is the
second thing here binding a certificate to a site, and a second implementation of an
`IIS:\SslBindings` write is the worst kind of copy to let drift),
and the two file helpers every script here needs: `Read-JsonFile` — which answers
**three** states rather than two, `$null` for a file that is not there, the parsed object
for one that reads, and a **throw** for one that is there and is not JSON, because the four
callers that care answer that last one differently (`Get-DeployConfig` fails, `Resolve-DbPath`
falls back to the default database, `install-iis.ps1` leaves the file it cannot read alone,
`update.ps1` carries on with the Windows service), so a helper that caught it would be
choosing one of those four answers for all four. `dev-run.ps1` is the fifth call site and
answers none of them — it stages a tree it owns, under `$ErrorActionPreference = "Stop"`,
where a corrupt config should stop the run. It reads a JSON **object**: a top-level array
comes back unrolled, a one-element one as the bare element and an empty one as `$null`,
which is this function's own word for "no file", so an array file still needs trap seven's
`@(... | ForEach-Object { $_ })` — `dev-run.ps1`'s pid file is the one of those here and
deliberately does not come through it. And `Write-JsonFile`, which is trap six written down
once: no-BOM UTF-8 through `[IO.File]::WriteAllText`, the path resolved first because .NET
has its own current directory. `dev-run.ps1` dot-sources this file for those two alone,
having held the second copy of that writer; it resolves no settings and calls no
`Initialize-DeploySettings`. Then: a `deploy.json` (next to the scripts, else
at the repo root, else `-ConfigPath`) supplies `installDir`, `port`, `baseUrl`,
`distDir` and the certificate names, and anything passed on the command
line wins over the file. Dot-sourced rather than a module — these run from a copied
`tools\` directory on a server where nothing is installed. `deploy.json` is gitignored;
`tools/deploy.example.json` is the template.

### `tools/install-iis.ps1`

Installs the server under IIS via HttpPlatformHandler (see ADR-0001). Elevated; supports
`-WhatIf`. **Disables the `AssetManagerServer` service** — both would bind the same port.
Settings (`installDir`, `port`, site/pool names, certificate names) come from
`deploy.json` next to the script or at the repo root — see `tools/deploy.example.json` —
and any of them can be overridden on the command line, which always wins. On an
interactive run it **asks** for the install directory, port, site name and pool name — and,
on a `-SelfSigned` run, the certificate names, since a wrong one there strands every client
— each offered with the value it resolved as the default and Enter accepting it, so whoever
is at the console does not have to know `deploy.json` exists. A setting passed on the command
line is not asked about. Nothing is asked under `-WhatIf` or on a host with nobody to
answer — `UserInteractive` alone is not enough to tell, since a scheduled task running as
a logged-on user reports true with no console attached — and there the missing-setting
failure stands instead. That covers a `-PfxPath`'s password too: nothing is imported under
`-WhatIf`, so a rehearsal is not stopped for a password it will never use, and a real run
with no console to ask on **fails** naming `-CertThumbprint` rather than hanging on a
`Read-Host` nobody can see. The password is never a parameter — it would land in the
console history and in transcripts. **Elevation is checked before the questions**, so an
unelevated shell is told to elevate rather than told about a missing `installDir`: true,
but never the reason it was not going to work. **A first-time setup needs no certificate source at all**: where none was
given, `InstallDir` holds no `ssl_cert.pem` and the site has nothing bound, one
is generated here the same way `-SelfSigned` would and the run says so, naming
the fingerprint - that being the one run where "give a certificate source" is a
demand the operator cannot satisfy, there being nothing on the machine to point
at yet. It generates on a host with nobody to ask as well, this being the
absence of an alternative rather than a question, and `-WhatIf` generates
nothing and prints what it would have made. **All three conditions have to
hold**, because an existing certificate is never regenerated: every client pins
`ssl_cert.pem` and fails closed against anything else (rule 1), so a re-run that
minted a fresh one would strand the whole fleet in the middle of routine
maintenance with nothing said at the time - and the pem and the binding are
asked about separately rather than one standing in for the other, a site bound
to a certificate whose pem somebody deleted being an install with a certificate
still, and a pem beside an unbound site being a file clients may already hold.
Any of the three failing leaves the existing refusal standing. An explicit
`-SelfSigned` keeps its own meaning of *mint one now*, with the replacement
warning below, and `-CertThumbprint` or `-PfxPath` never reaches that branch.
The three conditions are `Test-FirstTimeCertSetup` in `_deploy.ps1` rather than
three lines here, and `deploy-checks.ps1` drives all four states over them: a
boolean written the wrong way round is what a source check cannot see, and this
script cannot be run by a gate.
`-SelfSigned` generates the certificate here rather than taking
`-CertThumbprint`/`-PfxPath`; it must carry `CA:TRUE` and an
**IPAddress** SAN as well as the DNS ones, because each client loads the file as its own
trust anchor and urllib3 asserts the SAN regardless of `check_hostname`. **The names
default to this machine's own identity** — its computer name, its FQDN where it has a
domain suffix, `localhost`, and its own IPv4 read off the interface carrying the default
route — rather than to one deployment's literals, which minted a certificate for
`asset-server` on every other machine: the SAN is asserted whatever the client asked for,
so a client that pinned that file failed closed with no way back. Where no IPv4 can be
determined **no `IPAddress` SAN is written at all**, an absent one costing only a client
configured by address where a wrong one costs all of them. Whatever
certificate it binds, the public half is written to `<InstallDir>\ssl_cert.pem` (backing
up any existing copy) — `GET /cert` serves that file and clients pin it. **Replacing a
file that is already there names both fingerprints**, the way `update.ps1` does and for
its reason: a client fails closed against a certificate it did not pin, so what the
operator has to decide at that moment is whether the outgoing file is the one the
laptops out there are actually holding, and one hash on its own can be compared with
nothing. It is the sharper version of that question here — a `-SelfSigned` re-run mints
a **new** certificate every time, so the warning fires on every repeat run — and the
outgoing digest is also what identifies the backup copy taken beside it. Both numbers
come from `Get-CertFingerprint`, the incoming one by its **DER** bytes rather than by a
path, the PEM being warned about not having been written yet:
`X509Certificate2.GetCertHashString("SHA256")` would be the same number and is not
available, that overload being .NET Framework 4.8 while Windows Server 2019 ships 4.7.2,
where a correct install would die on a missing method in the middle of a warning
(#110). Points
`web.config`'s `processPath` at whichever build `InstallDir` holds: `AssetServer.exe
serve`, or `python.exe "<InstallDir>\run_server.py" serve` for a source install. Set
`pythonExe` in `deploy.json` rather than relying on `python` resolving — the app pool
identity has its own environment, so the **full resolved path** is what gets written.
**Every value interpolated into `web.config` is XML-escaped first**, which is not
housekeeping: a source install's `arguments` is the launcher path **quoted**, because it
can contain spaces, and a literal quote inside a quoted attribute closes it. The emitted
line was not XML at all, so IIS refused the whole file with 500.19 and never started a
process — which means `httpplatform-stdout` is empty and this script's own `/health`
probe warns and names a log with nothing in it. Source mode is the only mode (rule 14) and
IIS is the supported host (ADR-0001), so that was the whole of the supported deploy path;
exe mode passes the bare word `serve` and was never affected, which is why it went unseen.
An `&` anywhere in `InstallDir` or in the interpreter's path does the same thing more
quietly, being legal in a Windows path and an entity opener here.
`cascade-audit.py` holds it: every interpolation in that template has to name a value the
script escaped, and the template with hostile values in it has to still parse.
**Forwards the client's own address to the app** (#187): under this handler every
request reaches the app over a loopback hop, so `request.remote_addr` is
`127.0.0.1` for every client there has ever been, which is what `clients.address`
and `system_log.address` recorded on machines that reach this server over a VPN.
A rewrite rule sets `X-Forwarded-For` from IIS's own `REMOTE_ADDR` -
unconditionally, so a value a caller sent is overwritten rather than appended to,
these endpoints being unauthenticated by design - and `server.py`'s
`_client_addr()` reads it only where the peer is loopback, which under this
handler is every request and off IIS is none of them. The handler adds no such
header of its own, its configuration reference documenting exactly one it adds
and that being `X-IIS-WindowsAuthToken`, which this deployment has off. **URL
Rewrite is a prerequisite and its absence is a refusal, the same shape as
HttpPlatformHandler's** (#242 - it used to warn and let the install go on
serving loopback addresses forever; now it fails loudly, naming the download
URL, before the site ever starts): a site that started without the module was
a site that silently misreported where every client came from, which is the
failure the refusal heads off. For a deployment this refusal cannot reach -
one installed before it existed, or whose site has since lost the rule -
Connected Clients carries the same diagnosis in a footer line, where
`_iis_host()` answers something and every row is still a loopback peer. The
rule is written through IIS's own configuration
API in a step of its own rather than into the `web.config` template, because a
`<rewrite>` section in a `web.config` on a machine without the module is 500.19
over an unrecognised section - the site would not start at all - and because that
template stays one literal with nothing conditional in it, which is what
`cascade-audit.py`'s escaping check rests on. `HTTP_X_FORWARDED_FOR` is
allow-listed at `MACHINE/WEBROOT/APPHOST` first, a rule not being permitted to set
a server variable otherwise, which is why this script is elevated already. Both
halves are idempotent: the variable is added only where it is absent and the rule
is removed by name before it is added, so a re-run leaves one of each.

Grants the pool identity Modify on `InstallDir`, **and on the database's folder when
`db_path` puts it elsewhere** — on the folder rather than the file, because SQLite writes
`-wal` and `-shm` beside the database and without directory write access every submission
fails with "attempt to write a readonly database" long after this script reported success.
**Records the resolved `port` in `<InstallDir>\server_config.json` as well as in
`iis.json`**, because the port is one fact written down in two places and only the second
was being written: `server.py` reads `PORT` from that file at import, so an install on any
port but the default left the GUI probing a port IIS does not serve — OFFLINE over a
healthy server — and finding the default free, which is the exclusive-bind probe correctly
reporting that nobody is serving 8081 and the GUI then starting a second Flask over the
same database. It is a **read-modify-write**, for the reason `_save_server_cfg` is one:
overwriting the file drops `ssl_enabled` and turns HTTPS off on the next restart with both
cert files still on disk, and nothing looks wrong until a client fails to verify. An
unreadable file is **left alone and warned about** rather than replaced — every key in it
is a setting somebody chose and this script knows one of them. **It is no longer the only
thing that moves the port.** `bind-port.ps1` below is the elevated half the Server GUI
spawns when an Admin saves a new one (ADR-0021), and it writes both of these files the same
way for these reasons; `-Port` here still moves it as part of a full install, which is what
the console used to send an operator off to run by hand. **Both JSON files this
script writes go through `Write-JsonFile`**, which writes no-BOM UTF-8 through
`[IO.File]::WriteAllText` with the path resolved first, .NET having its own current
directory (trap six). They were written two different ways three lines apart until 054:
`server_config.json` had been fixed for that trap and `iis.json` beside it had not, so the
BOM was absorbed on the reading side instead — `_iis_host` decodes `utf-8-sig`, and still
must, because fixing the writer rewrites nothing already on disk. 054 kept that helper
**local to this script**, on the stated grounds that two writers inside one file is not yet
a pattern — which is about **call sites** inside one file. It is in `_deploy.ps1` now for
the other count: the **function itself** existed twice, here and in `dev-run.ps1`, and a
spelling this trap has already been got wrong on, written down in two files, is what rule
10 exists to prevent. Two, not three: 054 had already folded this script's own pair
together. `web.config` deliberately keeps
`Set-Content` and the BOM with it, being the one file here nothing reads with a plain
`open()` and the one whose own `<?xml encoding="utf-8"?>` declaration is what makes a
leading BOM something IIS and every XML parser already handle. Since 057 it is the
only `Set-Content -Encoding UTF8` left anywhere in `tools\`. **The `/health` probe at
the end goes through `Invoke-PinnedRequest`**, pinning the `ssl_cert.pem` it wrote a
step earlier: `New-SelfSignedCertificate -CertStoreLocation Cert:\LocalMachine\My`
puts the certificate in **My** and nowhere else, nothing here or in any runbook puts a
copy in `LocalMachine\Root`, and 5.1 has no `-SkipCertificateCheck` — so the probe
could not complete a handshake with the certificate this script had just bound, and
every correct `-SelfSigned` install warned that `/health` had not answered and sent the
operator to logs showing nothing wrong (#109). A warning that fires every time is one
nobody reads the time it is about a real 502, which is the only thing that check is
for; it now names what actually went wrong when it fires. Cutover steps, verification
and rollback:
`docs/runbooks/iis-cutover.md`; source mode: `docs/runbooks/source-mode.md`.

### `tools/bind-cert.ps1`

Rebinds the IIS site's https port to the certificate `ssl_cert.pem` names,
importing that pair into `Cert:\LocalMachine\My` first where it is not already
there with its key. Elevated; supports `-WhatIf`. Dot-sources `_deploy.ps1` and
does the work through `Import-CertPair` and `Set-SiteCertificate` —
one implementation of "rebind", two callers, `update.ps1`'s health-check
reconcile being the other.

**It recycles the app pool afterwards** (070), so a rebind and a process that
re-reads its files are one act rather than two. The server behind the site read
`ssl_cert.pem` at startup: a rebind that left the pool running would put the new
certificate at the edge over a process still holding the outgoing pair, and
`GET /cert` — the one channel a client refreshes over — would go on serving
the file that is no longer bound. The name comes from `app_pool` in `iis.json`,
which is why that file is now read whether or not `-SiteName` was passed; a
missing one is a warning and not a refusal, since the whole of what it costs is
a restart done by hand. `bind-port.ps1` ends on the same call for the same
reason, and `update.ps1` does not come through here — it cycles the pool
itself.

**`ssl_cert.pem` is the source of truth and the binding is corrected to it**,
never the reverse: that file is what `GET /cert` serves and what every client
has already pinned (rule 1), so a rebind the other way round would strand the
fleet rather than repair it.

**A script of its own because the console's cutover cannot rebind in process**
(C4, ADR-0020). Under IIS the server runs as the app pool identity and is not
an administrator, so it has to spawn something that is. `install-iis.ps1` is
the wrong thing to spawn: it is a full site install — it creates
the site and the app pool, rewrites `web.config`, re-grants ACLs,
read-modify-writes `server_config.json` and asks questions on an interactive
run — which is a pile of side effects nobody asked for when the
job is to swap a certificate. `update.ps1` does **not** call this either: it
already runs elevated, so it calls the same two helpers directly.

**Elevation is checked first**, before the settings are resolved, for
`install-iis.ps1`'s reason: an unelevated shell told about a missing
`installDir` has been told something true that is not why it was never going to
bind anything. The site comes from **`iis.json`**, the record `install-iis.ps1`
left of what it bound — the same file `update.ps1` resolves its
host from — and `-SiteName` wins over it for a machine whose site
was renamed in IIS Manager afterwards; an unreadable one stops the run naming
the flag rather than guessing, since binding the wrong site is a healthy server
presenting an unchanged certificate while this run reports success. **It writes
no `iis.json`**: that file is `install-iis.ps1`'s record, not an answer typed at
one rebind, which is the word `update.ps1` takes it at too.

**Both fingerprints are printed**, through `Get-CertFingerprint` like every
other place here that names one, so the number matches what the Server GUI
shows, what the client's first-contact prompt shows (ADR-0010) and what
`update.ps1` prints — and never a thumbprint, which is a
different hash of the same certificate and reads equally plausibly against any
of them. The outgoing one is read off the **binding** through
`Get-BoundCertThumbprint` rather than off any file, since what is being replaced
is what IIS is actually presenting. A site already bound to this certificate is
a no-op that says so. Pure ASCII, like every `.ps1` here.

### `tools/bind-port.ps1`

Moves the IIS site onto another port, in seven idempotent steps: the port into
`server_config.json`, an https binding on the new port **beside** the old one
carrying the same certificate, a firewall rule for it, the port into
`iis.json`, an app pool restart, a wait of `-Grace` seconds, and then the old
binding and its `SslBindings` entry removed. Elevated; supports `-WhatIf`,
which prints all seven and changes nothing. Dot-sources `_deploy.ps1` and
resolves the site and the app pool out of `iis.json` the way `bind-cert.ps1`
resolves its site.

**The grace window is the whole shape of it.** While the old binding is still
answering, `/health` on the old port advertises the saved number as
`next_port`, and every online client records it on its 15s tick and falls back
to it — then to `last_known_port` — when the old port dies. The default is 120
seconds, which is eight of those ticks; `-Grace 0` removes the old binding at
once, which is a decision about the fleet rather than a shortcut. A move that
took the old port away first would strand every client that had not been told.

**A script of its own for `bind-cert.ps1`'s reasons, and it is the same
pattern** (ADR-0021): under IIS the server is the app pool identity and cannot
touch a binding, a firewall rule or an app pool, so the console saves the
number and spawns this. `install-iis.ps1` would move the port too and would
also recreate the site and the app pool, rewrite `web.config`, re-grant ACLs
and ask questions on an interactive run — and it takes the old binding away in
the same breath, so it has no grace window at all.

**It writes `iis.json`, where `bind-cert.ps1` deliberately does not.** That
file is `install-iis.ps1`'s record of what it bound; which certificate is on
the port is not a fact it records, and the **port** is. A script that moved the
binding and left that key alone would leave the record naming a port nothing
serves, and that record is what `update.ps1` and the Server GUI's banner both
take at its word. Both writes are **read-modify-writes** through
`Write-JsonFile`, for `install-iis.ps1`'s reasons: `server_config.json` also
holds `ssl_enabled`, `iis.json` holds five keys this script does not know
about, and both are read back with a plain `open()` on the Python side.

**The certificate is read off the binding before anything is added**, through
`Get-BoundCertThumbprint`, so it is what the old port is presenting and not
whichever https binding a resumed run happens to enumerate first. The bind
itself names the port rather than going through `Set-SiteCertificate`, which
resolves the port off the site's first https binding — ambiguous by design
during this move. The old port's firewall rule is left alone: it is what the
grace window is served through. Pure ASCII, like every `.ps1` here.

### `tools/vendor.ps1`

Vendors one role's dependencies into `lib-<role>\` via `pip install --target` from the
pinned `requirements-<role>.txt`. Does two things beyond running pip, both load-bearing:
**strips every `.exe` pip leaves behind** (see rule 12 — the first run of this removed
`idna.exe` and `normalizer.exe`, and the server role's `pythonservice.exe`), and **stamps
`lib\PYVER`** with the Python minor version so `applaunch.py` can refuse a mismatch (rule
13) — `package.ps1` and `bundle-client.ps1` read that stamp back through
`Get-VendoredPyVer`, so a directory left half-written by an
interrupted pip run is caught at package time rather than on an engineer's laptop. What
each does about one differs: `bundle-client.ps1` refuses, while `package.ps1` runs this
script for that role with `-Clean` and carries on — the half-written tree goes
rather than being installed over, and the answer to a lib nobody has vendored yet is to
vendor it rather than to print the command for somebody to retype. Neither treats a
**stamped** lib as anything but current. `--no-compile`, so the `.pyc` files do not land in a manifest carrying the build
machine's paths; measured cost is ~1.4s on first launch. The interpreter is
**resolved through `Get-Command` before it is invoked**, and `$Python` carries
the full path from then on: `$ErrorActionPreference` is `Stop`, so a name that is
not on PATH raises a terminating `CommandNotFoundException` at the `&` and the
refusal written underneath it - the one naming `-Python` and saying to pass a full
path to `python.exe` - never ran for the case it was written for. The exit-code
check stays beside it, for an interpreter that is there and does not run;
`install-iis.ps1`, `dev-run.ps1` and `package.ps1` all resolve first for the same
reason, and `cascade-audit.py` holds every script here to it.

### `tools/bundle-client.ps1`

The one implementation of "stage a client's source payload", in two shapes.
`-App notifier|storekeeper` writes the engineer-facing, exe-free zip
`dist\<version>\<App>-<version>.zip`, carrying that app's sources, `common.py`,
`ui_kit.py`, `applaunch.py`, `client_update.py`, the launchers, `installer.py`, the
vendored `lib\` and a `README.txt`. `client_update.py` is in the payload because
it is what applies the **next** zip this script writes: leave it out and an
install can only ever be updated by running the installer again, which is what
it exists to stop. `-StageTo <dir>` puts the same payload — **both** apps, one installer
serving both — into a directory for `package.ps1` to hand to PyInstaller, and returns
before the manifest, the README and the zip. What an install consists of and what a zip
needs in order to install *itself* are two lists here (`$Payload` and `$Vehicle`), which
is what lets the staged payload and the zip's payload be one list rather than two copies
free to drift. A module only one app imports is neither of those: `$Apps.<key>.Extra`
carries it beside that app's `Source`, which is how `notifier_pending.py` reaches a
Notifier install (#208) without the Storekeeper's zip carrying and installing a file it
never imports. `Source` and `Launcher` stay exactly one name each — `cascade-audit.py`
reads that pair to work out what a zip holds, and `Extra` is the list it adds to it.

**`-App` left out is both apps, one zip each** - a release needs both, and asking for
them one at a time is a step to forget, which is a server advertising a client package
it does not hold while every installation of that app goes on being sent to the
installer instead. It is two zips rather than one holding both, because a zip is one
app's install: `New-MemberMap` is asked once per artefact, so the Notifier's zip
carries no `storekeeper_app.py` and neither carries the other's launcher. `-StageTo`
is the case that genuinely takes both, in one directory, and is unchanged. **`package.ps1`
calls this shape itself** since #190, into the same `dist\<version>\` it is already
writing, so a release directory carries the two zips without anybody remembering a step;
running it by hand is for a zip wanted outside a full release run. The temp
directory the zip route builds in is `$tmpDir` and deliberately not `$staging`, a
variable name in PowerShell being case-insensitive: that is `$Staging`, the flag the
member list reads to decide whether `installer.py` travels, so a second turn of the
loop would read a path as truthy and write a zip that cannot install itself. The same
trap named the function's parameter `$which` rather than `$apps`, which is the `$Apps`
table it would have shadowed.

**Neither route ships `ssl_cert.pem`.** A client given none confirms the server's
fingerprint on first contact (ADR-0010), so `-CertPath` is gone rather than carried
unused. Manifest records `mode`, `python_version` and a SHA-256 per file. Same
private-key refusal as `package.ps1`, plus a blanket refusal of any `.exe` (rule 12) and
the `Get-VendoredPyVer` check on `lib-client\`. `-StageTo` refuses a directory that is
not empty rather than mixing a payload into whatever was already there. Run `vendor.ps1
-Role client` first — not folded in, so one vendored lib serves both client bundles and a
slow pip install is not repeated. Measured 7.9 MB and 488 files for
`NotifierApp-2.3.0.zip`, against 43.6 MB for `AssetManager_Setup.exe`, which carries both
apps and a Python runtime.

### `tools/dev-run.ps1`

Runs the whole system locally for behaviour testing: stages a directory per app under
`.dev\` (each app resolves `config.json`, `assets.db` and `ssl_cert.pem` next to its own
source, so one shared directory would make them collide), copies the sources in fresh each
run (plus every module of ours that app imports - `common.py`, `ui_kit.py`
and `client_update.py` beside each client - since each staged directory is
its own import root and nothing else of this repo is on the path; `$ClientShared`
is a list nothing generates, closure-checked by #234 so that a name reached only
through another staged module cannot go missing from it), writes
the configs, and starts server + Storekeeper + one Notifier per `-Engineers`
name. `-Https` generates a self-signed 127.0.0.1 certificate and hands the public half to
each client; `-Reset` wipes the tree; `-Stop` kills what it started (matched on pid
**and** process name, so a recycled pid is never killed); `-Headless` runs the server as
`server.py serve` instead of opening its Tkinter GUI (the clients still start);
`-ServerOnly` skips the clients; `-AdminPassword` seeds `admin_config.json` (default
`admin`) as a **pre-ADR-0008 bare SHA-256**, since the salted helpers are in `server.py`
and this computes the digest in PowerShell — the staged server rewrites it in the salted
format the first time that password is used, which is the same path a real install takes;
`-DevDir` moves the staging tree off `.dev\`; `-PythonExe` picks the interpreter,
otherwise it is resolved from `PATH`. **A module missing from a staged directory is not a
degraded run**: that app dies on its own import block, and the console is hidden, so the
pid is still printed, still recorded in `dev-pids.json` and the script still ends on
`Running` - `client_update.py` was missing from both clients from the moment it landed, and
every behaviour test run here was server-only until 081 without anything saying so. Which
is why `cascade-audit.py` derives the list from what each app actually imports rather than
holding it against a fourth copy written down somewhere. Every config it stages is written through
`_deploy.ps1`'s `Write-JsonFile` and the one it read-modify-writes — the staged
`server_config.json`, whose `host`, `port` and `ssl_enabled` it owns and whose other keys
it keeps — is read through `Read-JsonFile`: it is the only script here that dot-sources
that file without resolving a single setting from it. Consoles are hidden and each app's output goes to
`dev.out.log` / `dev.err.log` beside it. Prints a few rows of the lookup sheet, because a
submission is refused for any asset the sheet does not know and that is the first wall
anyone hits.

### `tools/_devtools.py`

The three jobs PowerShell cannot do — `cert` is called by `dev-run.ps1` alone, now
that 061 has taken `package.ps1 -SelfSigned` out, `icon` only by `package.ps1`,
and nothing else calls any of them.
`cert` writes a self-signed certificate for the names it is handed, each becoming an
**IPAddress** SAN or a DNS one depending on whether it parses as an address, alongside
`CA:TRUE`, each of which fails silently if omitted (urllib3 asserts the SAN
even with `check_hostname` off, and OpenSSL 3 refuses a non-CA certificate as a trust
anchor). The names are arguments rather than the hardcoded `localhost` / `127.0.0.1` pair,
because the second caller mints for the real server's `asset-server` / `192.0.2.100`;
given none, that dev pair is still what it writes.
`lookup` prints the first rows of the sheet.
`icon` writes the `.ico` PyInstaller stamps on `AssetManager_Setup.exe`, the one exe
built here since 061, through
`ui_kit.write_ico` rather than writing it here — the installer writes one too, for a
source-mode Desktop shortcut, and which of the seven sizes go in is the decision worth
having in one place. Each is drawn from `ui_kit.app_icon` at that size rather than
downsampled from one 256px image, and a committed `.ico` would be a second copy of an
artwork the windows and the trays already draw, which is the file that would go stale
because nothing reads it back to notice. Python because PowerShell has no
X.509 generation, no xlsx reader and no way to draw a `.ico`, while the dev machine
already has `cryptography`, `openpyxl` and `pillow`.

### `tools/cascade-audit.py`

Checks the repo against the cascade rule above: one check per row of that rule's table,
comparing every fact this project writes down twice against its other copies — the four
`APP_VERSION`s, `PASSWORD_MIN` in `server.py` against the copy `installer.py` has to
keep because it cannot import the server (rule 10) — read off each module's own
body by AST, since a comment naming the bound is not an assignment of it, and a file
that has stopped stating it at all is drift rather than the quiet skip a missing
name would otherwise be — then `PERMISSIONS` vs `PERMISSION_LABELS` vs the count `CONTEXT.md`
states in words - taken out of the **Permission** entry rather than out of
the document, since that phrasing is the glossary's house style and a search
over the file answers with whichever entry sits highest: where the hijacked
number agreed with the code by coincidence, the real entry was free to say
any number at all. An entry that is not there, or one that has stopped
stating a count, is drift rather than the quiet skip it used to be -
this being the gate on that count, a check passing by finding nothing is
the failure this script's own docstring records twice. Then `CAPABILITIES` vs `CAPABILITY_LABELS` vs the labels this file names, the engineer
list in three places, all six tables' columns (including `init_db()`'s idempotent `ALTER
TABLE`s) against the schema block here - and, because that pair of readers is the
thing being trusted, a **synthetic** table put through both, carrying a column
name with a digit in it. Every column in this repo is spelled a-z, so the repo
cannot demonstrate that defect and a check waiting for such a column to be added
is one that reports clean until the day it matters: the `ALTER TABLE` walk read a
name with `\w` and the `CREATE TABLE` walk and the schema block each read one with
`[a-z_]`, so `addr2` was a column to one half and not to the other. Documented
correctly it was reported as code-only drift, which is a gate crying about a repo
that has none; added in `CREATE` alone it was missed on both sides, the sets
matched, and an undocumented column was reported as identical. Then every Flask
route against the API table - and, beside it, that table's **Credential** column
against the `door(...)` declaration at each route (#209), the column being
derived from the declarations rather than written beside them, so this check is
the whole of what keeps it true - every
file in `tools\` against the table it is in, the `.ps1` files' ASCII-ness, that each one
resolves an interpreter through `Get-Command` before invoking it (a
`$LASTEXITCODE` refusal written under an `&` is unreachable while
`$ErrorActionPreference` is `Stop`) — and, beside it, the **indirect** shape of
that same rule, which the first check could not see: `Resolve-ServerRunner`
decides the name in `_deploy.ps1` while both callers invoke it a file away as
`& $runner.File`, so neither end looks wrong on its own, and it handed back the
bare `python` where no `pythonExe` was set. So that function has to resolve
through `Get-Command` itself, and anything invoking a runner's `File` has to
have taken it from that function rather than deciding what to run a second
time — each package
manifest against the payload it carries, every path the docs name, and migration
contiguity. It holds **a release directory to carrying the client update packages** (#190): the names
agreeing across those four places is only half of it, since a server serves
`GET /download/client/<key>` out of `dist\` beside it and `dist\<version>\` is the unit
carried to a machine, so a release holding the setup exe and not the two zips is a server
that tells every installation it is behind and offers it nothing. Nothing else here can
see that — it is a property of what a build run produces — so what is asserted is
that `package.ps1` invokes `bundle-client.ps1` in **both** of its shapes, the `-StageTo`
one for the payload PyInstaller embeds and the zip one for the packages a client updates
itself from, read off the splatted hashtable each call site builds (trap eight: only a
hashtable splat binds by name, so an array splat is reported as unreadable rather than
passed). It holds **what a client install consists of** to its two copies: `$Payload`
in `bundle-client.ps1` plus that app's own `Source`, `Launcher` and `Extra` is what goes
into the zip and into what PyInstaller embeds, and `SOURCE_FILES` in `installer.py` is what gets
copied onto the machine, so the two are one set per app. Neither drift direction says
anything at the time it is made: a name only in the bundle rides along uninstalled and
the app dies on the import under `pythonw.exe`, while a name only in `SOURCE_FILES`
stops `_payload_mode` calling the payload a source one at all, so the installer declines
the payload it is carrying without naming the file. **`dev-run.ps1`'s staged directories
are the third copy of that same fact**, and the one nothing held: it is derived rather than
compared, each app's staged list having to cover every module of ours that app's import
closure reaches - transitively since #234, not just what the app itself imports - since
a staged directory is its own import root and a name missing from it is
the app dying on its own import block while the run goes on printing a pid and ending on
`Running`. **`package.ps1`’s `$SourceFiles` is the server’s copy of that same fact**, and
until 059 it was the one nothing pointed at: the group below asks only that every name
already in it is a file git tracks, never that every module the server imports is in
it. It is held to the module-level import closure of `server.py` and `run_server.py`
over the files of this repo — transitively, the same closure the `dev-run.ps1` group
has followed per staged app since #234; what still tells them apart is what each is
held against, one list for the whole server here and one per staged app there.
What needs it is a module no app names, reached only because another
staged module imports it: a zip can be built without it, and the install then dies
on that module’s own import line, silently, under `pythonw.exe` (#222, #234).
A module in the closure
the list does not name **fails** — that file is not packaged, and the server dies on
the import on the machine it was installed to, under a service host with no console.
A name the closure does not reach is **noted** rather than failed, being either dead
weight in the zip or a lazy import no AST walk can see, and a gate that cannot tell
those apart should say so rather than go red on the guess. The list carries more since
056 pointed `SHIPS` at it: a module that never reaches it is invisible to the manifest
drift check as well, so one omission costs the package and the check that would have
reported the package stale. It holds the **three appliers of
`lib\`** to replacing that directory wholesale - `installer.py`, `client_update.py` and
`tools/update.ps1`, one rule written down in three languages in three files that cannot
read each other: each has to clear the directory rather than merge a new pin set into the
old one (rule 13), and the two that keep a rollback have to keep `lib/*` out of their
per-file save and restore as well. `update.ps1` is what that check was written for - it
wrote `lib\` file by file and never cleared it, so an update, a downgrade and a failed
health check each left a tree that was neither release's. It holds **`install-iis.ps1`'s
`web.config`** to being well-formed: that is the one file here built by string
interpolation and then parsed by something that is not ours, and IIS refuses the whole site
over a character rather than ignoring the attribute. Two claims, and the second is what
keeps the first true - every interpolation in that template has to name a value the script
ran through its escaper, and the template filled with a quote, an ampersand and an angle
bracket has to still parse. It was written for a source install's `arguments`, which is the
launcher path quoted, because it can contain spaces, and was closing its own attribute. It holds the **Storekeeper's
role label** to agreeing on both sides of the
wire - `"%s (Storekeeper)"` worded once in `server.py` and once in
`storekeeper_app.py`, because the server does not import `common.py` (rule 10)
so there is nowhere for one copy to live - and the default name behind it to
agreeing in all four of its homes. Drift there is invisible: half the System
Log would read `(Storekeeper)` and half `(storekeeper)`, and a filter over the
column matches one of them. It holds **`ui_kit.fit`'s call count** to the sentence that states it:
the three app sources are parsed, every `ui_kit.fit` call is counted, and the
four numbers the `ui_kit.py` row writes out in words have to be those counts. That
row is where the cascade rule's last line - re-derive a documented measurement
from the source - had never been applied to a number of this file's own: it said
twenty-three windows, twelve of them in the Server GUI, while the Server GUI alone
had twenty-three call sites and the Storekeeper had eight. Nothing showed it,
because the only reader of that sentence is somebody deciding whether a window
they are adding is ordinary. A count rather than a list of window names, since a
list is what drifted: two stages of one window each call `fit`, so what can be
measured is call sites and what cannot is a judgement about windows. It holds the
**palette** the same way, in the
direction rule 10 actually wants: `ui_kit.DARK` is the table, `ui_kit.Theme`
binds those names into the app it is handed, and an app that assigns one of
them at module level is drift - a restated colour that has drifted is a
widget the retint walk cannot recognise and so leaves dark in a light
window. The other half is asserted too, since deleting the copies rests on
it: `Theme.__init__` has to bind, and a `_bind` reached only from the theme
switch would leave those names undefined until somebody changed theme.
It also enforces rule 10 at the one place it has
bitten, for both password doors: `/auth/verify` has to be paired with a fallback to `/admin/verify` for a server
that predates it, and only `common.py` may call either — a second copy is how a security
fix comes to be made twice and be right once. Each half asserts **exactly one** call, and
for the admin door that it sits in `verify_admin_password`: `verify_password`'s fallback
goes through that function rather than asking the endpoint a second time, so one is the
honest number in both halves. The enclosing function is found by which one the call node
is in, not by which one mentions the URL — a docstring saying why a call is elsewhere
would otherwise answer for it. The test is which module *calls* it, not which mentions it,
so a comment saying why the call is elsewhere does not fail it. It holds **what an app
writes beside itself** to being gitignored: each of the eight modules names those files
once, as a module-level `NAME = os.path.join(<DIR>, "<literal>")`, so the set is derived
rather than kept in step by hand, and an app run from a source checkout writes every one
of them into the repo root — where an untracked file is what `package.ps1` refuses to
build over, which is how `seen_proposals.json` (#71), `update_rollback\` (#104) and
`iis.json` (#105) were each found by somebody trying to package a release rather than by
this list. The answer is read out of `.gitignore` rather than asked of `git check-ignore`,
which cannot be asked this question: a bare `lib` comes back unignored, `lib/` being a
directory pattern and nothing on disk saying that name is a directory, while
`update_rollback/` came back *ignored* against a blank line — so a pattern's trailing
slash is dropped and a name matches whichever kind it is, the AST saying what the app
calls the thing and never whether it is a file or a directory. A name git already tracks
is reported as that rather than demanded to be ignored, `migrations\` being one. It holds a
**comment block above a function to being about that function**: a block naming
some other function of the same file and not the one it sits on was left behind
by whatever landed in between, which is what happened to the nine lines on why
`Resolve-Switch` takes a `[bool]` - trap three below, and a bug that shipped here
- when `Resolve-ServerRunner` was inserted above it. Nothing else says so: the
file parses either way, and the next reader of `Resolve-Switch` finds no reason
beside it not to give it the `[switch]` it looks like it wants. Reads only, so it is safe
to run any time; **exits non-zero on drift**, so it can gate a release — run it before
`package.ps1`. A manifest behind HEAD is drift only when a file that actually ships moved
in between, so a docs-only commit does not fail it — and **what ships is derived, not
listed**. It is the same `_named` the committed-payload check below builds: every
top-level `$Name = @(…)` list in the two release scripts, plus each app’s `Source`,
`Launcher` and `Extra`. Only `migrations/` and `requirements-` are kept by hand, being
prefixes rather than names and reaching a zip because `package.ps1` walks them into one
rather than naming them. It was a hand-kept copy of that set until 056, and by then it
had drifted in six places — the three registers, `server_cert.py`, `client_update.py`
and both of `$ToolFiles` — while each of 050-055 edited that one line to add its own
module and none of them noticed the rest. A derivation that comes back empty is
reported rather than compiled: a pattern matching nothing does not fail, it calls every
manifest docs-only and passes the whole group green. **And only the current
`APP_VERSION`'s packages are judged.** A package for a version already released is
stamped with the commit that released it and its payload has moved since by definition -
that is what shipping the next version means, not drift - so walking every directory
under `dist\` failed this group on every run for ever, and no rebuild could make a 2.3.0
zip green again. A gate that is red before the change is a gate nobody reads, which costs
more than the row was worth. Older versions are noted and passed over; a version
`server.py` does not state leaves every package judged the way it was, so an unreadable
version cannot turn the group into one that measures nothing. A manifest it cannot **read** is drift
too, named as such: it is decoded `utf-8-sig`, since a package built before 057 moved
`package.ps1` and `bundle-client.ps1` to a no-BOM `WriteAllText` carries a BOM (trap
six below), and one that is neither
JSON nor text is reported against its package rather than raising — a gate that dies is a
gate nobody can run, and it then exits non-zero saying the script crashed rather than what
drifted. It holds **what a release is assembled from** to being committed: every
top-level `$Name = @("…")` list in `package.ps1` and `bundle-client.ps1`, plus each
app's own `Source` and `Launcher`, has to name files git tracks. That is the dirty-tree
refusal's own property asserted from the other end — `git status --porcelain` does not
report an ignored file, so a staged name nobody tracks is invisible to the one check
that exists to make a manifest's commit describe its payload (#108). Read as every such
list rather than as the four by name, since the one that went wrong was a fifth nobody
was looking at; an element that does not look like a file — a component name, a
version — is not a claim about the repo and is left alone.
Two blind spots it was born with, both of which reported a clean repo that was
not: it walked only `*.ps1` and so never saw `_devtools.py`, and it split the API section
on `---`, which is also a Markdown table's own `|-------|` separator row and truncated the
table to nothing. It holds **an https probe to being able to verify what it is probing**: no `.ps1` in
`tools\` may reach `Invoke-WebRequest` or `Invoke-RestMethod`, neither of which can be
pinned and neither of which has `-SkipCertificateCheck` under 5.1, except at the two
sites that are not probing a self-signed server — `package.ps1`'s `Get-CertFromServer`,
which is *fetching* the certificate and so has nothing to pin to, and `dev-run.ps1`'s
plain-HTTP probe under its `-not $Https` guard, which answers the same trap by declining.
`update.ps1` and `install-iis.ps1` have to name `Invoke-PinnedRequest`, and `_deploy.ps1`
has to define it. An absence is what is being asserted and nothing here stands up IIS, so
it is a source check for the reason the certificate-bootstrap group in `server-checks.py`
gives (#109). Beside it, it holds **a warning that a certificate is being replaced to
saying which certificate**: a `Warn` line in `tools\` saying something replaces one has
to name a fingerprint in the block it opens, and there have to be **two** such warnings,
so one reworded past the check reads as drift rather than as a clean run. Source for the
same reason, nothing here standing up IIS or a client to read a warning off (#110).
Beside that, it holds **`update.ps1`'s rollback to putting back every file it
replaced**: the list a rollback restores is built from the package manifest, which
cannot name `installed.json`, so that file has to be added to it and the save and the
restore have to read that one list — a rollback that leaves the state record naming the
version it rolled back sends the next run to the wrong `rollback\<version>\`
directory (#111). Source again, nothing here standing up an IIS host to run an update
against. And it holds **a switch named in `tools\` to being a switch that exists**:
every `<script>.ps1 -<Flag>` written anywhere in these files — a `<# #>` help block, a
Python docstring, a `#` comment, a line of code passing one on — has to be a parameter
that script's own `param()` block declares. These scripts explain themselves by each
other's flags throughout, and 061 deleted `package.ps1 -SelfSigned` while leaving two
sentences resting on it: a reason whose subject is gone sends the next reader looking
for a flag, finding nothing, and unable to tell which of the two is stale (#112). It
reads the **whole line** rather than the part after a `#`, since three of the four
places these sentences live carry no `#` at all — and a docstring is where the drift it
is named for was sitting.
Python, not PowerShell, because every check parses Python or Markdown
and it never runs on a server — it reads no `deploy.json`.

### `tools/server-checks.py`

Behaviour checks for `server.py` — the companion to `cascade-audit.py`: that one checks
whether the repo contradicts itself, this one whether the server does what it is supposed
to. **Exits non-zero**, so it gates a release the same way — run all four before
`package.ps1`. Same idiom deliberately: plain Python, **standard library only, no test
framework**, because `requirements-server.txt` feeds a vendored `lib\` pinned to one
Python minor version (rule 13) and a test dependency has no business in it. `tools/server_checks/stage.py` **stages a
copy of `server.py` in a scratch directory and imports that**, never the repo's copy —
every path in `server.py` resolves next to the source file, so importing the repo's copy
reads the developer's own `server_config.json` and *writes* their `admin_config.json` at
import time, because `ADMIN_CFG = load_admin_cfg()` runs at module level. Same reason
`dev-run.ps1` gives each app its own directory. Drives the API through Flask's own **test
client** rather than a socket: no port to pick, nothing to fail to stop, and it works on a
machine where 8081 is already served by the real thing.

**The checks live in `tools/server_checks/`, one module per group of them** — 047 split
18,758 lines in one file, which was larger than `server.py` had been before 035 and 036
lifted two modules out of it. `stage.py` is the shared half: the one staging tree, built
once at import, the sources the source-reading checks parse, `ok()`/`bad()`/`eq()` and the
counters the last line of a run adds up, and the fixtures more than one group reads. One
tree for the whole package rather than one per module, since a second staging tree per
group would multiply the setup cost the shard numbers below measure, and the groups hand
each other no state - each builds the database it needs and tears it down, which is what
made the split mechanical and is what makes any slice of the groups a valid run. A
fixture only one group reads sits in that group's module, beside what reads it.

**`stage.py` also wraps the staged `ui_kit.fit`** (095). Every call records the
window's title and requested height, and a window asking more than 688px - what a
768px screen leaves once `fit` has clamped it - fails on the spot unless it has a
direct-child `tk.Canvas` holding a windowed `tk.Frame`, the shape `ui_kit.ScrollRegion`
builds. Judged at the call, so `--group NAME` alone still judges every window that group
opens. The `screen` group opens Asset Sync, Server Settings, Mail Settings and Add
Transaction and asserts the recorder saw each by title, so the recorder cannot stop
measuring without failing.

`tools/server-checks.py` itself is the front door, and the only list a reader needs: its
`GROUPS` names the group modules in the order they run. **Add a check as a `check_*`
function taking no arguments**, in the group module its subject belongs to; a subject
none of them covers gets a module of its own and a line in `GROUPS`. Within a module the
checks run in definition order, so a check runs where it sits. `tools/gate.py` knows
nothing about the package and does not need to - it runs the entry point, which still
takes `--shard i/n` and still exits non-zero - but its `MAP` carries a
`^tools/server_checks/` row beside the `^tools/server-checks\.py$` one, without which an
edit inside the package would match nothing and owe no gate.

**The two groups that measure the header band settle the window rather than flushing
it** (#204). `check_the_header_band_fits` and
`check_nothing_on_this_window_is_cut_off_at_a_narrow_size` resize the Server GUI and
read the result back, and a size asked for is not a size the window has - see
`docs/CODING_STANDARDS.md`. Both now repeat the settle until the band's measurements
come back the same twice running. It changed what they report: a clipped Copy URL at
1.75x that the unsettled read had been intermittently missing since #205, which is
also why `check_the_header_band_fits` drives one database state and not two - the
database came off that band with the defect. Beside them, the mail group waits ten
seconds rather than two and a half for its worker thread, patience costing nothing
on a green run and two and a half seconds not being enough when eight shards are
competing for the cores.

**Quiet by default, and shardable.** It prints the failures and one last line -
`all checks passed (N check group(s), M assertion(s), K skipped)` - rather than a line
per passing assertion, which was 2626 lines of `[OK]` nobody read; `-v` restores the old firehose.
`--shard i/n` runs every n-th group starting at the i-th, so `tools/gate.py` can run n
copies at once and aggregate the exit codes: 5m47s to 2m40s at eight shards. The slice is by position rather
than by name, so adding a group needs no list kept anywhere, and the counts on the last
line are what say a run asserted as much as the last one did - a group that quietly
stopped measuring shows as a drop in the count rather than as a clean run.
`--group NAME` runs one module of `tools/server_checks/` alone and `--list-groups`
prints the names, which is the flag to reach for while iterating: `--group settings` is
three seconds and `--group console` 1m58s against the 5m47s of all twenty-five. It is
by name where `--shard` is by position, so it is the one thing that needs the `GROUPS`
tuple, and the name is checked against it - a typo would otherwise run nothing and
report a green file of no assertions. Both flags are named on the last line of the run.
**An argument the parser does not know is refused rather than skipped past.** The scan
this replaced looked only for the flags it wanted and ran the whole file on anything
else, so `--help` printed nothing and ran for six minutes, and a mistyped `--shrad 3/8`
ran the entire suite while reading as a shard - silently, and green, since `gate.py`
aggregates exit codes rather than counts. `client-checks.py` carries the same parser,
`--group` included since #238 made it a package too. One group covers **every route declaring the credential it
wants** (#209): that every route in `server.py` carries a `door(...)` line, that
no declaration belongs to something that is not a route, that no route declares
a capability outside `CAPABILITY_REMOTE` - `ssl_cert` above all, rule 1 - and
that each declaration matches what its body actually reaches, a route declaring
`open` being held to calling none of the credential checks and one declaring a
capability to asking `_remote_admit` for **that** capability, resolved through
`_member_door` and `_mail_door` rather than written down a second time here. Its
negative half is the sweep itself: the route count and every declaration
kind are asserted, so a parse that found nothing fails rather than reporting a
clean sweep for ever. A second group asks the **server** the same question
rather than the source: every route is sent the request three ways - no
credential, a wrong password, the right one - and the answers are held against
the declaration, a capability route opening for the admin password and for its
own capability password alone, an `admin` or `own` route refusing every
capability password, and a route declaring `open` never answering 401 at all.
That last one is why it exists: a route declared open and in fact guarded is
this ticket's defect written the other way round, and no reading of the source
catches it once the declaration and the body have been made to agree and both
are wrong. It forces `_remote_tls_ok`, the test client not being TLS, so what
it asks about is the credential and never the transport - the groups that own
the transport rule are the ones that turn it off again. Another covers the **stored password format** (ADR-0008):
that a stored value is salted and self-describing, that two installs given the same
password store different values, that a pre-ADR-0008 bare SHA-256 still verifies and is
rewritten in place on use in all three of its homes, and that a rewrite which fails does
**not** turn a correct password into a refusal — it builds the legacy form itself rather
than asking `server.py` for one, since the point of that branch is to read a value this
build would never write. Another covers the **Own Password lifecycle** (ADR-0009): that an
Admin-set password is Temporary and a cleared one takes the flag down with it, that the
Engineer replacing it is what clears the flag and an Admin can re-arm it, that one
Engineer's password does not open another's row, that the admin password is the reset
path, that a capability password is refused there like everywhere else, and that a
passwordless Engineer still has their Transactions listed, Confirmed and Rejected with no
password at all — plus the column arriving by migration `006` and by `init_db()` alike,
and its `down()` keeping it. Another covers the **Lookup Sheet living in the database** (024): that the `assets` table arrives by migration `009` and by `init_db()` alike and that `down()` keeps it with every row, that a first run reads the embedded workbook in and a later start does not seed over what an Admin has since changed, that `GET /asset_types`, `GET /lookup` and rule 6 all answer off the table, that what `GET /lookup/file` exports is what `POST /lookup/upload` puts back unchanged - the workbook being the interchange format on both sides of that - and that one write touches one row while the one writer refuses an asset with no type or no identifier. Two more cover **an identifier naming one asset** (025): that `init_db` declares both identifiers `COLLATE NOCASE` and creates both partial unique indexes, that two rows differing only in case are one collision while two empty identifiers are not - an asset may carry only a serial - that correcting an asset is not a collision with itself, and that `POST /lookup/upload` refuses a workbook colliding with itself, writes nothing at all and names the row rather than calling the workbook invalid. Beside them, migration `010` both ways: the collation and the indexes on, every row kept, the index refusing a second row for one Asset Number, `down()` putting the byte-matching back - and the pair of answers a database that already collides gets, the migration refusing and naming it while `init_db()` warns and starts, which is the one place in this repo where the two paths deliberately differ. Beside them, the seed over a sheet that contradicts itself - the shipped one does - reading every asset in, clearing the shared identifier from all but the first, saying so in the System Log and leaving the server with a Lookup Sheet rather than an `IntegrityError` on its first boot. One more opens the **Lookup Sheet window and its asset form**, which nothing opened before 026 although both are in the list of dialogs measured against their own children above - that group reaches Database Location by its status chip and the button through to this one is inside it - so both are measured here as well as asserted on: that Asset Model is an editable combobox rather than an Entry, that it lists the models this sheet has for the Asset Type picked and re-reads them when that type changes, that a type with no model yet offers nothing rather than everything, and that a model in no list is still saved with no question asked about it - the question is stubbed and reaching it is the failure. The two helpers every other group here uses moved with it: they fill and empty the table now, and an unreadable `asset_lookup.xlsx` is staged before the first `init_db()` of the run so the 3462 embedded assets are not read into every database this file makes. Another covers the **Engineer's name being matched
without regard to case**: that a re-cased name updates the Engineer rather than
adding a second, that `/auth/verify`, `/pending` and the history filter all answer
for it while the **password stays case-sensitive**, and that the auto-approve read
finds the row while the Transaction records the Engineer's own spelling rather than
the caller's - plus the collation arriving by migration `008` and by `init_db()`
alike, `down()` putting it back without losing a row, and the two answers a
pre-existing collision gets: the migration refuses naming the pair, `init_db()`
warns and starts anyway, being the path that runs on every boot. The legacy table
is built by hand there, since the point of the rebuild is to read a shape this
build would never create.
Another covers the **Storekeeper's name** - that it is a setting read from
disk on every call rather than a row in `team_members`, that an empty or
missing one means the column default, that `/health` carries the bare name,
and that the row's `storekeeper` column and the System Log entry beside it
never disagree about who recorded a Transaction. The Server GUI's Add
Transaction is the leg that would go wrong silently, since it records `Admin
(Server GUI)` and a label derived from that column would read `Admin (Server
GUI) (Storekeeper)`; that it states its own `actor` is a **source** check, the
call being a Tk callback no harness reaches, and it is found as a call node
rather than by which function encloses it - `add_transaction` sits inside
`run_gui` and `do_add` inside `add_transaction`, so enclosing-function matching
answers three times for one call site. **Two groups are not about `server.py`
at all** - the certificate bootstrap is the second, asserting from both sides what may happen without an
answer: that a refusal, an app that registered no way to ask, no Tk loop to ask on and
nobody answering all pin nothing, that the fingerprint `common.py` shows is the same
string `server.py` shows for the same certificate, and - as a source check, since no
request demonstrates the absence of a second unverified path - that exactly one function
in `common.py` turns verification off, that only `bootstrap_cert` reaches it and only
`api()` reaches that, and that nothing anywhere in the file hands `requests` a falsy
`verify` in any of the shapes that has (a keyword, an attribute, a `setdefault`; the
pattern was widened after a planted one went through). **One group is not about
`server.py` at all** — `common.py`'s two password doors, `verify_password` and
`verify_admin_password`, from the client side: an endpoint's contract and the client's
reading of it are one fact checked in two directions, and for `verify_password` the leg
that matters most cannot be reached from a live server, since a server predating
`/auth/verify` is what answers 404 and there is no such server left to point at. So the
transport is stubbed and **which URL was asked for** is what gets asserted — that a 401
does not fall back is invisible in the return value, and so is the admin door's refusal to
fall back at all. What that door's refusal of an engineer's own password rests on is the
endpoint rather than the client, so it is asserted against `/admin/verify` itself in the
group beside `/auth/verify`'s. `common.py` is staged and imported the same way `server.py`
is. A gate script of its own for one function would be a third thing to run and remember.
One group is a **source** check about the certificate itself rather than the
fingerprint: that installing one and removing one each write a System Log entry
naming it, and - the half no request demonstrates - that `_cert_fingerprint()` is read
**before** the file is written or deleted, since afterwards the outgoing certificate
is gone and the call answers with the incoming one under its name. Both are Tk
callbacks behind a file dialog no harness can answer.

One group closes a **console window** and asks what that cost (#119):
that a form matching the file is not unsaved and its X asks nothing, that
an edited field is, and that Cancel leaves the window open with nothing
written while Discard closes it having written nothing either. It covered
the console's own close too until 089 - two windows open at once counted
and named in one question, and a Save all through each window's own save -
which went with `_console_close` itself: the console is the main window
now and its close is a hide to the tray, so it shuts no door on what it
opened and has nothing to answer for. Driven through the real
`WM_DELETE_WINDOW` handler with `askyesnocancel` replaced, because which
control asks and what is still open afterwards are things only Tk can
answer.

One group opens **Manage Transaction History** and drives real clicks at the
coordinates the select column reports (#123): that the window is named for the
action that opens it, that the box is the tree column and does not stretch into
the data, that the identifiers are still the first data columns (rule 4), that a
box ticks the row **and selects it**, that a second box **adds** rather than
replacing - the defect a plain click would cause, and the one thing here only Tk
can show - that a click on the data still selects the usual way with the boxes
following it, and that the header box selects everything and clears it again.
Every assertion reads the boxes and the selection together, since the one way
this can fail is by disagreeing with what Delete is actually holding.

Three groups **open the real window** and read widgets back off the screen, which is the
only way to see a defect of this kind: the action row's elastic layout, the certificate
fingerprint the Server Settings window shows (measured with a certificate beside the
server, since the group below opens that window in the branch where there is none), and
every window's size against what its own children ask for (six dialogs were smaller than
their form and each lost the button packed last, four of them entirely, and nothing static
sees that). An axis's **opening** size is judged only where that axis is fixed, since a
resizable window can be dragged open - and a window fixed on neither **says so**, with
its size and its children's beside it, because a window that prints no line at all is
indistinguishable from one the openers forgot: the System Log was both at once until
018, draggable on both axes *and* missing from the list, so the gate reported a clean
run over a window it had never opened. What such a window **is** judged on is its
**floor**: it can be dragged shut as well as open, and how far is a number the window
itself wrote down, so 019 holds each of the four at its own `minsize` and requires the
bottom control to still be mapped, button-sized and above the bottom edge - a control
that survives there can never be dragged away. One that sets no `minsize` has no floor
to judge and is a finding, for the reason 018 gives about silence. It has to be the real
window: `run_gui` configures the styles and fonts these forms are drawn with, and a
dialog measured without them asks for 24px less than it does in front of an admin. All
three skip rather than fail where Tk has no display. One group covers the **System
Log**: that `_log_event` is the one writer and an entry it wrote in process is
distinguishable from one that arrived over the
wire, that an impossible log write returns False and raises nothing **while a
Transaction is still recorded, confirmed and rejected** - which is the one
promise this feature is not allowed to break - that `POST /clients/log` caps
every field and the batch and answers an over-long one politely rather than
fatally, that the source address the server saw is stored beside a claimed
component rather than instead of it, that both retention bounds apply and the
hourly job still calls them, and - as a source check, since no request
demonstrates the absence of an argument never passed - that no `_log_event` call
anywhere in `server.py` names a password or hashes one. **Two groups beside it cover which address that column and `clients.address` record** (#187): a forwarded address behind a loopback peer is what lands, the same header from a peer that is not loopback is ignored and the peer lands instead - both, because a check that proved the header is read would pass just as happily against a server that reads it from anybody, and this endpoint needs no credential at all - no header at all records the peer, each of the three loopback spellings is the same peer, a chain is read leftmost, the value is capped since it comes off a header rather than a socket, and the check-in answers the same way, this being one helper serving two columns. Beside them a **source** check, an absence no request demonstrates: `_client_addr` is the only reader of `request.remote_addr` in the file, and something calls it, so neither half can pass by finding nothing. One group beside it covers the **Transaction's own two free-text fields**, which are the same argument one table further on: `notes` and a rejection `reason` arrive on unauthenticated endpoints, so a caller chooses their length, and `transactions` has no retention bound of either kind to trim an enormous row later - that both are truncated at `_TXN_TEXT_MAX` and **still recorded**, that the note's cap is in `_create_transaction` rather than at the endpoint, which is a source check since the other two callers are a Tk callback and an offline buffer, that the System Log entry the reason reaches is bounded beside it, and that an ordinary note comes back untouched. One group beside **that** is the same argument on the cancel path (#115), which is where it bites hardest: `POST /transactions/cancel` needs no password at all for a Pending Transaction while the Storekeeper switch is on, and absent means allowed — so an over-long `reason` and an over-long `cancelled_by` through that unauthenticated door each have to land truncated with the cancel still going through, the System Log entry has to say what the column says as far as `_LOG_DETAIL_MAX` lets it — agreement rather than two lengths, which is the half a stored length cannot show on its own — and an ordinary cancel has to come back untouched. Beside them the rule that a **blank** reason is still refused, so capping cannot come to stand in for it, and a source check that both caps are in `_cancel_transaction` rather than at the endpoint, that caller's other door being the Server GUI's ⦸ Cancel Selected, a Tk callback no harness reaches. Two groups cover **mail** (030), both against a stub SMTP rather than a server
on a port, for the reason this whole file drives Flask's test client rather than
a socket: that a host which is not there, one that never answers and a refused
login each come back as the mail server's own words with no exception escaping,
and that beside every one of them a Transaction is still recorded, Confirmed and
Rejected - which is the promise `_send_mail` is not allowed to break, the same
one `_log_event` makes. Then where the one **replayable** secret this system
holds is not: not in `server_config.json`, not in any System Log row, not in the
test mail, and not readable back by the dialog that sets it - with the settings
round-tripping through that file without it, and the DPAPI-less case asserted as
the **refusal** it is rather than skipped (ADR-0013). Beside them source checks
that three helpers and nothing else reach `smtp_secret.dat`, that the dialog
checks the admin password directly rather than through `_authorise`, and that
Server Administration is the door to it.
Three more cover **which** events are mailed (031): that a rule mails its event
and the absence of one mails nothing, that a hand-edited rule which cannot be
read is ignored rather than raised on, that a level floor holds, that a rule on
a `mail.*` event is never acted on so a failed send cannot mail about itself,
and that a rule written to the file takes effect with no restart. Then the two
bounds under a burst - six entries are one mail, the count it held rides the
next one that does send, and a hundred *different* events stop at the ceiling,
which is the half the per-event limit cannot do on its own. Then the promise
`_log_event` makes: a `_send_mail` that raises leaves the row written, the
writer still answering True about it, and a Transaction still recorded,
Confirmed and Rejected. Beside them a source check that `_notify_of` is called
from exactly one place and that place is `_log_event`.
One group covers **who owns
the process**: that `_iis_host` answers not-IIS for an `iis.json` that is missing,
empty, not JSON or not an object, and IIS for the one `install-iis.ps1` writes -
**with the BOM and without it**, since that script writes no-BOM UTF-8 since 054 while
every install made before it keeps its BOM until somebody re-runs it (trap six), and a
plain `open()` would report "not IIS" on every one of those machines, which is the one
wrong answer that function can give; that
`server.py` reads that file in exactly one place and `run_gui` asks once for all
three surfaces; and - opening the real window **both ways** - that the banner names
the site and the pool where the file is there and says nothing where it is not, and
that Server Settings asks `ui_kit.fit` rather than holding a written size on the branch
that adds three wrapped lines of warning to it. No other run of this file reaches that branch,
since no developer's machine has an `iis.json` beside the staged server - which is
also the regression worth proving, so the no-file case is asserted here rather than
left to the rest of the file happening to run that way.

One group covers the **proposals** (028, ADR-0012): what the unauthenticated
endpoint refuses on the spot and with which code - `bad_asset` for a row that is
not an asset, `duplicate_identifier` where the register already holds it (in
`_save_asset`'s own words) and `already_proposed` where a pending proposal does,
naming it - that a proposal is **not** an asset, so the register is unchanged and
`GET /lookup` still does not find it, that approving writes exactly one asset
through the one writer, that a rejection needs a reason, writes none and keeps
the row, that a rejected proposal blocks nothing, that an approval racing the
register is refused and **leaves the proposal pending**, and that every one of
them is a System Log entry. Beside them three **source** checks, the window being
a Tk callback no harness reaches: only `_propose_asset` inserts a proposal, only
`_decide_proposal` answers one, and that window writes no asset of its own.
A third covers a file of them (029): that `POST /assets/import/preview` writes
nothing and answers with 027's own three helpers, refusing a mapping that cannot
describe an asset rather than validating against it; that a batch is **all or
nothing**, so one row the register holds refuses the file and names the line,
and a file that collides **with itself** is refused as a file rather than having
its first row taken and its second told somebody else had asked; that a taken
file is one `proposed_at`, one System Log entry and still not a single asset;
and that the cap is answered with the count at both doors. Beside them source
checks that both importers read `_check_import_mapping`, that `_propose_batch`
goes through `_validate_import_rows` and `_propose_asset` rather than writing,
and that the preview writes nothing at all.
A second group holds migration `011` to the both-ways pattern - `up()` creating
the table and its index, twice over changing nothing, `down()` dropping the index
and **keeping the table and every row on it**, and `init_db()` creating both the
other way.

Five groups cover the **external asset system** (032, ADR-0014), every one of them against a stubbed opener rather than a host on the network, for the reason this file drives Flask's test client rather than a socket: that a run **adds** what the register lacks, fills only an **empty** field, leaves a disagreement exactly as it was and says so, and leaves an asset the payload never mentioned alone - which is the whole of what a sync is allowed to do; that an answer which cannot be read, is not JSON, is not a list, or whose keys map to nothing is refused **whole** with the register untouched and `sync.failed` written, since half a payload applied is neither the external system's list nor the one that was there; that the credential is in none of the four places it could leak to - the config file, a System Log row, the window that sets it, or a plain `http://` request, which is refused outright; that every write goes through `_save_asset` and nothing in the feature deletes an asset or writes the table behind the writer, asserted as **source** since what is claimed is an absence, with the transport assertion scoped to `_sync_fetch` rather than to the file because `run_gui`'s own liveness probe reaches for `requests` over loopback for an older and different reason; and that the last run's outcome is derived from the log's own rows rather than from a stored key. Beside that one, that a run started at the console stamps the clock the scheduled one counts from: the loop was the only thing stamping it, and what that cost is invisible from either end — the console reports a run that worked and the schedule reports a run that worked, and only the external system's own logs show the two reads a minute apart. Beside them the window is opened and measured with the rest.

One group holds the **import** (027) at its two helpers rather than at the window, which is a Tk callback behind a file dialog no harness can answer: what that window does is ask, and the answers it asks about are `_map_import_columns` and `_validate_import_rows`. A header is guessed under punctuation, case and spacing and whatever order the columns sit in; one that cannot be guessed is left **unmapped** rather than pointed at the nearest thing, and a column is claimed by one field only; an `.xlsx` and a `.csv` of the same rows read back identically, blank rows above and inside the data dropped and every cell stripped; a row is refused for each of the four reasons - no identifier, no Asset Type, an identifier the Lookup Sheet holds (named in `_save_asset`'s own worded-once sentence) and one an **earlier row of the same file** holds, which is a distinct sentence naming that row; asking writes nothing; and the commit writes exactly the rows that passed, leaves what was already there untouched - this door adds where `POST /lookup/upload` replaces - and logs one entry saying how many were refused. Beside it, that an **Asset Type folds onto the spelling the sheet already has**: `LAPTOP` and `laptop` against a sheet holding `Laptop` both become `Laptop`, so the commit leaves one type rather than three and `GET /asset_types` serves every client that one list; a type the sheet really does not have is carried through as typed and is still what the window asks about; and a sheet already holding two spellings folds onto the **older** row's, `_load_assets` being ordered by id, so an import does not quietly move assets from one spelling to the other.

One group opens the window **with a tray** - the only one here that does, a tray icon being a thread and an image - and holds the tooltip to the banner on the branch where nothing answered, which is the branch that was wrong: the title was a literal `RUNNING` whatever the port was doing. It points the probe at a port nothing serves rather than at the configured one, since this gate runs on machines where the real server is up. Beside it a source group asserting that one site writes that title and it is `set_health`, that the protocol there comes from `_ssl_active` rather than from a second read of `ssl_enabled`, and that the icon is not built claiming `RUNNING` before anything has been asked - with the tray still having to be there at all, so neither half can pass by finding nothing. **Since #176 there are four more beside it.** The window is opened with a tray over five states — an IIS site with a certificate bound, which is the production one (a thumbprint in `iis.json`, `ssl_enabled` false, `ssl_cert.pem` beside the server and **no** `ssl_key.pem`), an IIS site with nothing bound, an IIS site **serving TLS that `iis.json` has no thumbprint for** (#185, the probe stubbed, which is the one state a record-only reader cannot see), and off IIS with the pair and without it — and what is read back is the scheme the liveness probe actually asked for and the protocol the tray title carries, the defect having been those two disagreeing with the site. The scheme is read off a stub of `_loopback_get`, the transport both console probes share, and no longer off a stubbed `requests` - which is how a probe that could not complete a handshake went on passing here until #280. Beside it a source group holding the decision to one place: `_iis_tls_bound` reads `iis.json` once, `_remote_tls_ok` and `run_gui` each ask it once, `run_gui`'s body names `ssl_enabled` exactly once, and `refresh_stats` carries no copy of any of it and does read `_ssl_active`. Since #185 `_port_serves_tls` has to exist, be called from exactly one place in the file and that place `_iis_tls_bound`, and carry no `requests`, no `urllib`, no `/stats` and no `GET` - it is a handshake and must never become a second liveness probe. And since #186 the probe itself has to name no `CERT_REQUIRED`, no `load_verify_locations` and no `SSL_CERT_PATH`, say `CERT_NONE` outright rather than leaving it to a default, **and carry no credential at all** - that last one being what the first rests on, since a password over a session that verifies nothing is a client trusting a server, which is rule 1 and is exactly what this is not. Since #280 `_loopback_get` is held to the same, with no `headers` and no falsy `verify` in either. **And #280 added the two that drive the real thing**: a TLS listener on loopback over a certificate `make_cert` mints for the run, through which `_port_locked` has to read the `port_locked` served, both ways, and `refresh_stats` has to paint the health mark SUCCESS and then DANGER once the listener stops; and Server Settings opened over a real `iis.json` in four states, whose SSL Certificate status has to read `Active (HTTPS)` under a bound thumbprint with no `ssl_enabled` and no `ssl_cert.pem`, and read as it always did off IIS. Then the two repaint groups, both driven rather than read, since what is claimed is that a tick did **not** do something: the CLIENTS box has to hold the same widgets across two ticks with nothing checked in and a rebuilt set once one has, and `_make_server_tray_icon` has to be called once for CHECKING and once for the first answer and then not again while that answer holds **Since #189 there are three of them**, and the third is the count the other two were standing in for: a real listener takes the port, so the window is the monitor-only one production runs as (ADR-0001), and `ui_kit.Surface.refresh` and `tk.PhotoImage` are counted across two ticks over an unchanged answer and have to be **zero** - they were one and ten per tick. Both halves, a banner that never repaints being the worse bug: the listener is then taken away and the ring has to go from SUCCESS to DANGER.

One group asserts the **app icon** on the real window: that the root is given one at
every size in `ICON_WINDOW_SIZES` and lets them go when it closes. The reference is what gets read, since Tk has no query form
for an icon — and that reference is the load-bearing half anyway, an unheld
`PhotoImage` being collected out from under the title bar.

One group holds the **migration runner's own contract**: that a step which raises
leaves the database exactly as it was - no scratch table, every row, `user_version`
unmoved - so the re-run has something to do and can do it, that a step which finishes
is committed rather than left open, and that a finished step is not undone by a later
one failing. Driven through `run_migrations` against a migrations directory written for
the check rather than against `008` and `010`, because the contract belongs to the
runner: what it buys is every rebuild written after it, not those two.

The group that measures the **action row** answers in both directions since #91. It lays the row out at five widths on the real window, and then holds the numbers **this file** states to what it just measured — a documented measurement re-derived from the source, which is what the cascade rule asks for and what nothing was doing. Beside it a source group asserts that no comment in `server.py` carries a width for that row at all: six did, three of them the 978px of 982px from before Copy Server URL moved to the banner, and two of those three sat five lines apart on two Pills in one feed header, describing the same row as seven-at-978 and as six full labels. Both scans are scoped to the **clause** the number sits in rather than the paragraph around it, because three rows on that screen are measured and the other two sit in sentences that open by saying *not on the action row*, so a scan over the paragraph answers for whichever row the sentence began with. Since #92 the source scan covers all three: the chip row and the side panel had a width apiece in `server.py` and two and three copies in this file, which is the same setup one ticket earlier, and a width for either may no longer come back into the code. Beside it the group that lays the **header band** out, which is #205's successor to the two #92 added: the URL block and the four counts against the width the band has at the 940px minimum and at the opening size, in both database states, since a moved database grows the status line under the URL by a parent folder. It is held to no figure written down anywhere, for the reason the chip row and the side panel it replaces were not: what the band spends is this machine's hostname, address and database path, which is a fact about the machine rather than a number this repo decides - so what is asserted is that every block on the band is given no less than the width it asked for, at both sizes and in both states, and that CLAUDE.md states a figure for it nowhere. The four engineers each holding an asset are still set up, so the counts are counts of something.

One group holds **the three controls on this window that ran past the box they had** (165). The group above measures placement, and that is what let these through: `pack` answers a row that will not fit by **shrinking** a child rather than by refusing it, so a control cut off at its right-hand edge and one that fits are the same measurement from outside. What is asserted here is that every child is given **no less than the width it asked for**, at two display scalings and at the longest hostname a deployed machine can answer - both halves of the family being a written-down pixel width meeting font-measured content, so a gate run at 100% against a machine called `srv1` measures neither. That length is **fifteen characters** (#257): the band builds its URL from `socket.gethostname()`, which on a domain-joined Windows machine answers the short computer name rather than the FQDN, and Windows caps that name at fifteen. The shim is patched onto **both** the staged `server.py` and the staged `server_gui.py` - the band reads `server_gui.py`'s own `import socket`, so until #257 the shim reached nothing and the band measured whatever the gate machine was called. Two sites since #205 took the chip row and the side panel away: the header band, whose Server URL is what a long hostname overflows now, and the status line, which has to sit **below** the action row. **The band is driven with digits in its count cells since #258**, which is the half of this that was never measured: `refresh_stats` probes `127.0.0.1:PORT/stats`, nothing answers in the harness, and every count was therefore the offline em-dash - one narrow glyph where a deployment has four numbers that grow with it, so the leg measured a state no running server is in and passed. One, three and six digits now, with the window's own timers cancelled so a settle long enough to cross a five-second tick does not have the placeholder written back under it. And what is asserted with them is what a shortfall cannot be read off: the Server URL block and Copy URL are still drawn, and the counts left on the band are the **front of `_COUNT_KEEP`**, which the check reads off `server_gui.py` rather than keeping a second copy of - a band that gave up `waiting` and one that gave up `out of store` measure identically from outside. The third site is the Storekeeper's and is in `tools/client-checks.py`.

One group covers **which asset a Transaction is about**, which is a SQL
expression rather than a column — a Transaction carries no `assets.id`, it
records the identifiers as they were typed — and was written out three times
before #88: in `/stats`' `out_now`, in `_gui_snapshot`'s `held` and on both
sides of `_cancel_transaction`'s newest-per-asset equality, held together by
nothing but a comment saying they were the same rule. It is `_asset_key_sql`
now, and this group asserts **both halves**: as **source**, that the wording
occurs in that one function and nowhere else in the file, which is an absence
and so has no request that demonstrates it; and as behaviour, that the Out Now
tile and the per-Engineer rows beside it count the same assets, and that Cancel
asks the same question a third time. **The rows have to be ones the two
spellings actually part company on**, which took two goes to get right: a
serial-first copy was planted and the first set of rows counted the same under
both. The shape that discriminates is **two Asset Numbers sharing one Serial
Number** — the manufacturer's number that identifies nothing, which migration
`010` found 6 times in the shipped sheet's 3462 rows: reading the Asset Number
first they are two assets, reading the Serial Number first they are one, so the
tile and the rows come out one apart and the older of the two stops being
cancellable. An asset carrying only a Serial Number and two Asset Numbers
differing only by case are in that table for what they pin down rather than
what they discriminate — that the fallback leg is exercised at all, and that a
Transaction still records the spelling that was typed where the `assets` table
folds the two into one asset.

One group holds **a delegate's act to being logged as a delegate's** (#74): that `_authorise` answers `"capability"`, `"admin"` or `""` rather than a bool, that `_console_actor` words both attributions in one place, and — the half with a row to read back — that a Transaction corrected on the Manage Transaction History password writes `transaction.modified` naming the delegate while the same correction on the admin password still reads `Admin (Server GUI)`. The other four are **source** checks, being Tk callbacks behind a confirmation or a file dialog: each of `do_delete`, `do_save_cfg`, `import_archive`, `do_install` and `do_remove` has to ask `_console_actor` and has to carry no actor literal of its own, which is the absence that stops the defect coming back invisibly.

One group holds every **password length bound** to the constant that states it. `PASSWORD_MIN` and `CAPABILITY_MIN` exist so that number is one fact, and six doors refuse a short password - four helpers, two endpoints and the Server GUI's Change Admin Password - so the group asserts that all six name a constant, that no door compares a password against a number of its own, and that no window states the bound with a digit in the sentence. Source, because the dialog is a Tk callback no harness reaches and what is claimed is the **absence** of a second copy of the number; beside it a behaviour half raises the constant and requires the endpoints and `_set_member_password` to move with it, without which the group would be asserting the spelling of a number nothing reads. The door that was wrong is the one that matters most: the admin password is what every capability password is measured against, so a literal there is the credential at the bottom of the system being the loosest one in it.

Two further groups are **source** checks rather than behaviour, and deliberately
— the two certificate paths that used to write `server_config.json` themselves are GUI
callbacks no harness can reach, and the hourly Auto-Accept job is a daemon thread whose
exceptions are swallowed, so nothing would otherwise report that the loop had stopped
calling the rule. The Engineer list is a third: only `_save_member` inserts an Engineer
and only `_delete_member` removes one, only `_rename_member` renames one, Manage Users goes
through all three and not through `_authorise`, and `/members` has exactly its **four**
endpoints since #171 — `list_members`, `add_member`, `delete_member` and `rename_member`,
that last one forwarding to the one writer of a rename — the window is a Tk callback no
harness can reach, and what is asserted is the absence of a second writer rather than the
behaviour of the one that is there. The count is written out rather than sampled, so a
fifth door has to be added there deliberately. Beside them three behaviour groups #171
added: that the **Server Settings** capability password opens all four Engineer acts and
each is attributed to the delegate, that the three write doors **tell the two credentials
apart over plain HTTP** — the capability password refused `insecure`, the admin password
this door's own and still working, which is the wire-compat half a transport gate in front
of the password would have broken — and that `GET /permissions` serves the captions rather
than letting a client copy them (rule 8).
One group beside them puts **Mail Settings and Notification Rules on the
network** (#172) and asserts the property that move is about: the SMTP password
is the one replayable secret this server holds, so a channel that can *set* it
has to be one that cannot *read* it, and the four places it could leak to are
each checked - the answer to `GET /admin/mail`, `server_config.json`, a System
Log row, and a plain `http://` request, which is refused `insecure` with
nothing written. Beside them the three things the wire adds: an absent
`smtp_password` keeps what is stored while `""` clears it, a rule written
through the endpoint takes effect with **no restart**, and a recipients list
sent straight back from the GET is still a list rather than a stringified one.
The password legs follow `HAS_DPAPI` rather than being skipped without it - a
machine that cannot encrypt one has to **refuse** it naming the reason, which is
ADR-0013's rule and the half a skip would stop asserting. Beside them source
checks that the console window and each endpoint go through the same three
writers, that neither write door reaches `_save_server_cfg` behind
`_save_mail_settings`, that the GET never calls `_smtp_secret_get`, and that all
five routes ask one `_mail_door` which is `_remote_authorise` - strict on both
credentials, these routes being new enough that no install sends the admin
password to them over plain HTTP.
One group drives **what `/version` advertises against what `dist\` actually holds**
(#190): a server holding nothing still publishes its own `APP_VERSION` as `latest` and
advertises no package at all, with `GET /download/client/<key>` refused `no_package`;
a zip in `<dist>\<version>\` is advertised by its own filename, at its own route, with
the digest of its own bytes and their length, and the download serves exactly those bytes
— driven against real bytes rather than read, since the digest is what the updater
checks a finished download against **before** the running app is stopped, so an entry
naming a digest of something other than what is served is an update that refuses itself
on every machine at once. The app with no zip beside it is not advertised, a zip carried
on its own beside `dist\` resolves as well, and the two that must **not** resolve are
asserted with them: a zip at some other version, left behind by an older release, and a
key `CLIENT_PACKAGES` does not hold. This is the half of #190 that lives on the server
— the likelier of the two answers a pushed `update_now` gives, *this server holds no
package for it*, is decided here rather than on the client.

One group beside them opens every console window that carries a masked field and drives a **real click** on the toggle #202 put inside it - unmasked, then masked again with **the field's own** mask, read off the entry rather than assumed - and asserts the count it found, a walk over every window that finds no masked field being a check that passes by finding nothing. Beside it the two **replayable** secrets, driven with a secret stored: Mail Settings' and Asset Sync's fields open **empty** and revealing one shows nothing, which is ADR-0013's and ADR-0014's own property asserted from the window rather than from the endpoint. Driven rather than read for the reason the helper exists: the control is placed *inside* the entry, which a source read sees as a call and not as a widget that is there and wired. The **server URL on the status card** is a fourth, and the plainest: what is
asserted is that `run_gui` builds it from `socket.gethostname()` and that no
hostname literal and no read of the bind address is left in it — an absence,
in a window no harness opens far enough to read the string back off.

### `tools/client-checks.py`

Window checks for the three **client** apps - the third gate, run beside the other three
before `package.ps1`. Mostly one question: is each window in `storekeeper_app.py`,
`notifier_app.py` and `installer.py` big enough for the form inside it? Nothing static can
see that defect, and `pack` gives the shortfall to whichever child was packed last, which
in these apps is the button that submits or saves - five dialogs were short on an axis
`resizable(True, False)` leaves fixed, and two of them showed 1px of a 46px Login button.
Same idiom as `server-checks.py` deliberately: plain Python, **standard library only, no
test framework** (rule 13), `check_*` functions taking no arguments, **exits non-zero**,
and skips rather than fails where Tk has no display.

**The checks live in `tools/client_checks/`, one module per group of them** - #238 split
8,980 lines in one file, the way #221 split `server-checks.py`. `stage.py` is the shared
half: the one staging tree, built once at import, the sources the source-reading checks
parse, `ok()`/`bad()`/`eq()` and the counters the last line of a run adds up, and the Tk
helpers every window group measures with - `measure()`, `run()`, `opened()`, `quiesce()`
and their kin. One tree for the whole package rather than one per module, and the groups
hand each other no state - each builds the app and window it needs and tears it down,
which is what made the split mechanical and is what makes any slice of the groups a
valid run. A helper only one group reads sits in that group's module, beside what reads
it.

`tools/client-checks.py` itself is the front door, and the only list a reader needs: its
`GROUPS` names the group modules in the order they run. **Add a check as a `check_*`
function taking no arguments**, in the group module its subject belongs to; a subject
none of them covers gets a module of its own and a line in `GROUPS`. Within a module the
checks run in definition order, so a check runs where it sits. `tools/gate.py` runs the
entry point, which still takes `--shard i/n` and still exits non-zero, and its `MAP`
carries a `^tools/client_checks/` row beside the `^tools/client-checks\.py$` one, without
which an edit inside the package would match nothing and owe no gate.

**Quiet by default, and shardable.** It prints the failures and one last line -
`all checks passed (N check group(s), M assertion(s), K skipped)` - rather than a line
per passing assertion, which was 928 lines of `[OK]` nobody read; `-v` restores the old firehose.
`--shard i/n` runs every n-th group starting at the i-th, so `tools/gate.py` can run n
copies at once and aggregate the exit codes: 3m01s to 2m00s at four shards. The slice is by position rather
than by name, so adding a group needs no list kept anywhere, and the counts on the last
line are what say a run asserted as much as the last one did - a group that quietly
stopped measuring shows as a drop in the count rather than as a clean run.
`--group NAME` runs one module of `tools/client_checks/` alone and `--list-groups`
prints the names - `--group popup` is the four checks that drive the popup's real timers.
It is by name where `--shard` is by position, so it is the one thing that needs the
`GROUPS` tuple, and the name is checked against it: a typo would otherwise run nothing
and report a green suite of no assertions. `--check NAME` is one step smaller, one
`check_*` group alone with `--list-checks` printing the names, and was this suite's only
selector while it was one file: `check_the_storekeeper_windows_fit` is nine seconds
against 3m01s for all sixty-nine. Its names come off the functions `main()` collects, so
it keeps no list that can fall out of step. Every selector is named on the last line of
the run. An argument the parser does not know is refused rather than
skipped past, the same as `server-checks.py`: `--help` used to print nothing and run
for three minutes. Its own suite rather than more groups
in `server-checks.py`, which is server-shaped from its first line - it stages `server.py`,
drives Flask's test client, and every helper in it takes a database - while nothing here
touches a database or an endpoint. `tools/client_checks/stage.py` **stages copies of the
app sources in a scratch directory and imports those**, never the repo's: every path in these apps resolves next to
the source file, so the repo's copy would read and write the developer's own `config.json`
and `assets.db`. Same reason `server-checks.py` stages `server.py` and `dev-run.ps1` gives
each app its own directory. **No server** - `api` is replaced with a function that raises,
which is the offline path all three apps already handle; pointing it at `asset-server`
would file a check-in from whatever machine ran the gate. **The windows are measured
inside the real app**, built the way each entry point builds it, because an app configures
the ttk styles and fonts its forms are drawn with at startup and the same dialog under a
bare `tk.Tk()` asks for 24px less than a user sees. Each axis is judged only where that
axis is fixed, so a shortfall on a draggable one is reported as a drag rather than failed;
every dialog that calls `ui_kit.fit` is then forced onto a 150px-tall screen and its
bottom control has to still be mapped, on the screen and button-sized. One group beside them holds every masked field in the three clients to carrying #202's toggle - the Storekeeper's Admin Login and Cancel, the Notifier's setup wizard, Admin Login, Change My Password and both states of Remote Admin, and each of the installer's three forms, since the component radio rebuilds the form under it and a Server install's two password fields exist on one of the three - each opening masked, unmasking on a real click on the control rather than on the handler behind it, and going back to **its own** mask, which is what keeps the one site masking with `\u2022` from being restyled to the house `\u25cf`. Beside it the Remote Admin Mail panel against an answer saying a password **is** stored: the field opens **empty** and revealing it shows nothing, that panel never being told what is stored (ADR-0013) and being the sharpest case of the rule, this one being on the network. Two groups are
**source** checks: no client window may take its size from a branch (an `ast.IfExp` inside
a `geometry()` argument - the form no sweep for geometry literals sees), and only
`ui_kit.fit` may size one, so a fourth copy of `_fit` cannot appear in an app.
**`stage.py` wraps the staged `ui_kit.fit`** the way the server suite's does (095): a
window asking more than 688px that does not scroll fails at the call, and the `screen`
group opens Remote Admin on its Mail panel, fed answers so it is measured holding
something, and asserts the recorder saw it.
One group is about what this app does with a server that has stopped answering: `api` is made to raise `ReadTimeout` and then `ConnectTimeout`, and both have to end in the same place - the Transaction in `pending_buffer.json` and the storekeeper told it was saved offline rather than shown a failure. Both, because what is asserted is that the answer follows the situation and not the class, and only one of the two was ever wrong. Beside them a refusal the server actually made, which must **not** be buffered, so the group cannot pass by finding a buffer that takes anything.


Two groups are about neither a window nor a client app but **`applaunch.py`**, which is
what Windows starts in source mode and the one thing here that has to work when the
install is broken: it is staged beside the three apps and deliberately kept out of `APPS`,
having no form for the size groups to measure. What is driven is the reporter with each of
its two doors taken away in turn - user32 alone, tkinter alone, neither, and both, since
which one answers is an import resolved at call time and no source read sees it - and,
with neither, that the failure is still logged, still exits non-zero and still raises
nothing out of the diagnostic path. The second drives `bootstrap` end to end against an
app that raises, asserting that the exception's own last line reaches the box while the
whole traceback stays in the log. A third drives `_add_pywin32` over a staged
`lib\` (#188): with `win32`, `win32\lib` and `pywin32_system32` in it all three
have to be reached - the DLL directory beside the two path entries, since
without it `win32crypt` is found and then dies on `DLL load failed`, which is
the same failure one layer down - and with none of them nothing may be added
and nothing may raise, that being every client install, the client role pinning
no pywin32. Driven rather than read because what is asserted is the state of
`sys.path` and of the DLL search path after the call, with the call site itself
read off the source: the bootstrap group above runs against a `lib\` carrying
no pywin32, so nothing there would notice the call going. Beside them a fourth
holds the Python step to asking for
Tcl/Tk, with the other four install flags asserted alongside it. One group is about
neither a window nor a client app but the **updater**, which was staged
beside them here and loaded by nothing, so `client_update.py` had no gate at all: that its
phase one refuses a manifest naming a file outside the install - absolute, drive-lettered,
UNC, `..` past the root, or nothing but dots - while a name that walks up and back is
still accepted, and that the `launcher` is held to the same rule. Asserted against **phase
one** because that is the whole of the split: a refusal there is a message box the app
goes on running from, where by phase two the old files are already gone and what is at
stake is whether the rollback can still find them.
The Storekeeper's **Propose an Asset** and **Propose from a File** windows are
measured with the rest - the second opened past its file picker, which is the
only part of it this file cannot drive - and the two legs after them are that
app's offline answer to each: the `api` this file stubs raises, which is the
real offline path, and what is asserted is that the form says the server cannot
be reached, says nothing was **queued**, stays open with the question unasked,
and leaves `pending_buffer.json` untouched - a proposal is a question and not a
Transaction (ADR-0012), and twenty of them queued into a state the app cannot
see is twenty the storekeeper believes were asked.
One group is about neither a window nor a client's own decision but what a client does with an answer: the
Storekeeper adopting its name off `GET /health`. The three ways of saying nothing - an
unreachable server, a server too old to carry the key, an empty value - all have to leave the
name this installation already had, since a server that predates the key would otherwise blank
it on its first heartbeat and every entry after that would be attributed to nobody; and the
name has to reach `config.json`, because `app.started` is logged inside `__init__` before any
heartbeat is answered. And the other way the name is lost, which is not the heartbeat's at
all: a `config.json` naming nobody has to leave the run recording under the column default,
which is what `load_cfg` reading the file over a copy of the defaults rather than into them
buys - beside a name that *is* a name, still read out of that file, so the group cannot
pass by ignoring it. Beside it, a source check that no Transaction body in that app names a
storekeeper outright - those three bodies are reached through a server this file deliberately
does not have, so a literal left in one would only surface as a Transaction recorded under the
wrong person months later. One group is about where a **bulk row the server never answered** ends up (#95): `api` raising `ConnectionError` under Bulk submit has to leave every row in `pending_buffer.json` carrying the Engineer and the direction the window was set to, out of `_bulk_queue` so a second click cannot send it twice, and reported as saved rather than as still listed. Driven rather than read, since what is asserted is where the rows are across two places at once, with a refusal the server actually made as the positive half — not buffered, and still in the list — so it cannot pass by finding a path that buffers whatever it touches. One group is about what a **bulk submit** writes down (#100): a stub that takes two rows, is refused on a third and answers 409 on a fourth inside **one** call, and the assertions are that each answered row is its own entry in the form's own wording - `transaction.submitted` at `info` and `transaction.refused` at `warn`, both attributed to the Storekeeper - that both halves of the log hold them, that the 409 writes none, since the form writes none for one either, and that what the window reported agrees with what the log holds. One call rather than a batch of one driven twice, because what is asserted is that the entry belongs to the Transaction and not to the batch. One group is about how often a flush asks a server that is still down (#99): five queued rows against one that accepts and never answers have to be **one** attempt, with every row still queued and still in order, and a row sent before it went must not be re-queued. What is measured is the number of attempts, since the buffer this leaves behind is identical either way and the cost is a hundred seconds of a frozen window per tick, the loop being on the Tk thread. Beside it the half that keeps it honest: a refusal and a 5xx are the server answering about one row, so both have to leave the rows behind them attempted, or the group would be asserting that a flush gives up on anything at all.

One group is about the **offline buffer's three answers** and is neither
a window check nor a static one: that a 201 and a 409 drain, that a 5xx and an unreachable
server stay queued, and that a **4xx leaves the buffer** and is shown in the server's own
words saying the movement is not recorded - with the row behind a refusal still sent.
Every answer but 201 and 409 used to go back in, so a payload the server will always
refuse was re-POSTed every fifteen seconds for ever, which no endpoint answers for and
no static read sees. One group is about neither size nor identity but the **app icon**: that each of the

wrong person months later. One group is about what this app writes down when nothing answers: a Transaction it buffered. Both offline legs are driven - the server already down when Submit was pressed, and the server going between the lookup and the submit - and both have to end in one `transaction.buffered` entry naming the asset, the Engineer and the direction, at `warn` and attributed to the Storekeeper. Both, because what is asserted is that a buffered Transaction is logged and not which `except` caught it, and only one of the two ever was. **Both halves of the log are read back**, the shipped queue and the local file, since the entry was missing from both and they answer different questions. Beside them a refusal the server actually made, which is neither buffered nor logged as buffered, so the group cannot pass by finding a log that records everything. One group is about **what each of this app's two surfaces says about a movement, and in what order** (166, 078): that Asset No. and Serial No. come first in `COLS` **and** on RECENT's drawn row, which is a list row rather than a column set since 078 - rule 4 asserted against one of the two surfaces being a rule with a hole the width of the other, so the list's two identifier labels are read off the screen and the Asset Number has to be the one above; that the pane beside that list states the Asset Type, the model and the rejection reason `RECENT_COLS` dropped, the trip to History those columns cost being the thing 078 removed; and - the half only a driven fill shows - that a row put through History's tree lands with every cell **under its own heading**, a positional tuple written for nine columns into a tree holding seven listing serial numbers under Model, and that the pane **repaints**, two movements being selected older-first so a pane that painted once cannot pass by holding the right row.

One group is about a header control carrying its **whole label** (165): a `Pill` is built with a written `w`, measured at one display scaling, while the label inside it is `font.measure`d at whatever this machine is set to - so at any other scaling `Pill._fit` answers the only way it can, by eliding, and the theme button's `w=158` drew `Follow Wi...` on a 175% display, losing the mode and leaving a sun over `Follow Windows` and a sun over `Light` looking like one control. `Pill.fit_text` is the answer and this holds it, at **1.00x and 1.75x** and through all three modes: the defect is invisible at the scaling the number was written at, which is a gate measuring a number against itself, and only the longest of the three labels overflows. It reads `truncated`, `_fit`'s own answer about the string it actually drew, rather than a pixel width alone.

One group is about neither size nor identity but the **app icon**: that each of the
three apps gives its window one image per `ICON_WINDOW_SIZES` entry - Windows picks the
nearest of what it is handed and scales unfiltered when handed one, which is what a
crushed title-bar icon looked like - that every one of those sizes is also in the `.ico`,
that the window lets them go when it closes, that the
Notifier's badge is a different picture from the plain one, and that with no `pillow`
the drawing answers None and the window still opens. The release is checked because
of what it fixes - an image held past `destroy()` outlives the Tcl interpreter and
raises inside `tkinter.Image.__del__` during shutdown, printing an "Exception ignored"
traceback after this file's last line that reads like a failure and is not one. Beside it, one group reads the **shortcut VBScript** the installer would run rather
than running it — cscript would put a real shortcut on the Desktop of whatever machine
runs the gate — asserting that `IconLocation` appears only where there is an icon to
point at, that the target, the argument and the working directory still go in quoted,
and that the icon path is quoted like every other value: it is one string literal per
value, a single unescaped quote closes one early and fails the whole file to compile,
which is how source mode went release after release without ever creating a shortcut.
Beside that, that `write_ico` produces every size Windows asks an `.ico` for and
answers False rather than raising where there is no `pillow`, since the install has to
carry on with a plain shortcut. Three groups are about the colour each
window is drawn in: that no backdrop canvas is placed under it, and that a
band and every label on it read back as **one colour** - which is the step
074 deleted the render for, two labels side by side having sampled a
gradient at their own x. Compared with each other rather than each against
the token it was assigned, so a window that steps fails whatever produced
the step. One group is about what leaves this system: the
workbook's Summary against the rows it was written from. An Engineer the baked-in
fallback list does not hold has to be counted, one it happens to hold has to be counted
the same way - what is asserted is that no list plays a part, a list being what went
wrong - nobody who did nothing may be invented beside them, and the per-Engineer
counts have to add up to the Total on the same sheet. It calls `_write_excel` with the
rows rather than opening the window, the workbook being written past a file dialog no
harness can answer, and skips where `openpyxl` is not installed. Beside it a source check
that the writer names no engineer list at all and that `_open_export` hands the dialog the
one this installation was told about. Two groups are

carry on with a plain shortcut. One group is about **what the poll loop may be handed**:
that `poll_secs` clamps a `config.json` asking for `0`, a negative, something past the
ceiling or something that is not a number at all, and that the Settings form refuses the
same values on the window while a sound one saves and leaves every other key alone. Both
sides, because the field is not that file's only writer - and the reader is the half that
matters, `_poll_loop` being a daemon thread where a `sleep` that raises ends the poller in
silence rather than reporting anything. Two groups are

carry on with a plain shortcut. One group is about what a source install's shortcut ends up pointing at, which has to be a Python: `_gui_python` is asked with no `lib\PYVER` to go on, with `sys` replaced on the installer module rather than on the interpreter — frozen is a fact about the process, and setting it for real would answer for `_ssl_cert_source` and `_payload_root` at the same time — and what is asserted is that it asks the machine for the pinned series, that it answers with what came back and never with `sys.executable`, and that with nothing on the machine it answers None so the install is refused rather than shortcut to Setup. Beside them the branch the fix must not disturb, an installer run from source still answering with what it runs under, and the refusal itself, which has to name a version rather than the `None` it was handed. Beside it, one group is about **how often the installer may ask** about a certificate: a refusal is not re-asked in the same process, which is the clients' rule and is asserted here before the way out of it, and then an install attempt re-arms the question and the next one is offered - so a stray keypress on a dialog whose default button is Cancel costs that click rather than every click until Setup is reopened. A certificate already on disk is still not re-offered, the re-arming being the question and not the trust; and the caller is a **source** check, `_install` being a Tk callback needing a server, a payload and an install directory, so what is asserted is that the installer re-arms exactly once and does it there. One group beside it is about what the **Python install step** leaves behind, in both senses: a download refused by the signature check is gone from the machine afterwards while the refusal still reaches the operator, a copy shipped beside the installer is left exactly where it was and nothing is fetched to stand in for it - that file being the admin's and the one an offline machine was sent - and a run that works installs off the file it fetched, removes it too and warns about nothing, so the group cannot pass by finding a step that deletes everything and installs nothing. Beside them the **source** half, which is where the call is written: `_ensure_python` is asked for inside the same `try` that runs `_deploy_component` in both client installs, that being the one whose `except` puts a failure in front of the operator, and inside any other `try` it would say nothing - reachable no other way, since the failure needs a server, a payload and a machine with no Python on it. One group beside them is about **which certificate question the installer asks**: the one line `_report_unreachable` offers as a way out - accept the fingerprint when it is offered, or drop `ssl_cert.pem` beside the installer - is driven through `_ssl_cert_source` rather than through a file on disk, because the defect was that this reader asked by path where the three install paths asked that function, and an assertion that put a certificate next to the installer would pass just as happily against the wrong question. Offered where there is none to install, withheld where there is one, never mentioned over plain HTTP, and every answer still saying the server could not be reached rather than that a password was wrong. Beside it the **source** half, about the `getattr(self, ...)` defaults those three install functions read their fields through: each stood in for an attribute `_on_component_change` has always built before Install can be clicked, and the Notifier's stood in with a class rather than an instance, so `.get()` was an unbound function called with no arguments and raised `TypeError` inside a lambda where it reads as answering with the first engineer. An absence, so nothing driven can show one going or stop a differently-shaped one arriving. One group beside them is about **what a server reinstall keeps**: `_write_admin_cfg` is driven against a staged `admin_config.json` carrying two capability passwords, and what is asserted is that the map survives while `password_hash` moves, that a file which is unreadable or is not an object is left byte for byte alone and answered with the line the popup carries, and that a fresh install still writes the two keys it always wrote - without which the group would pass against a function that refuses everything. Beside them the source half: one function in `installer.py` names `admin_config.json` at all, the install calls it, and what it answered reaches the operator. Driven rather than read because what is claimed is the content of a file after a write, and reachable at all because that write takes paths and needs no payload, no service and no window. One group beside that holds **the password bound the installer refuses on** to being one copy of a number rather than two: no door in `installer.py` compares a password against a literal, no window states the bound with a digit in the sentence, and the constant that replaced them is module-level and read **twice** by `_install_server` - the refusal and the sentence under it - so a raise moves what the operator is told as well as what is turned away. It is the same pair of assertions `server-checks.py` makes about `server.py`'s six doors, and this is the seventh, which **sets** the admin password where all six of those change one that already exists. That the number equals `server.py`'s is deliberately **not** asserted here: that is `cascade-audit.py`'s row, and one fact held by two gates is a second place for it to be answered differently. Source, because what is claimed is an absence and because `_install_server` needs a payload, a Windows Service and a window.

Two groups are
about **which** window opens, or stops being open, rather than how big it is — both are Tk
callbacks nothing static reaches and no endpoint answers for. The Notifier's logon window
(090; its Admin Login until then) stubs the replacement form and the Settings window and
asserts which answer it acts on and with which arguments: that the password is checked
against the engineer picked, that a Temporary Own Password is replaced as the logon
completes and an admin password is not asked to replace anybody's, and that a refused
password or a check that could not be made logs nobody on. Beside it the two things 090
moved around that window: Settings opens through the app's own `_open_settings` with no
password and no Server-URL-only narrowing, and Log off clears the engineer, opens the
logon window and leaves the poll asking the server nothing. The Storekeeper's Server Settings gets the same
leg, against `common.verify_admin_password` rather than `verify_password`, and it rides in
that app's measurement group rather than a group of its own: the Storekeeper has one group
here and its Admin Login is already opened in it, so a second group would be a second place
to look for one app's answer. The Notifier dismissing a Transaction resolved
from the Dashboard uses the **real popup**, since what is asserted is that the window goes and the queue moves on and a stub
would answer for both: that the popup on screen closes, that every copy of a queued id is
dropped while another's popup is left alone, that an unrelated id changes nothing, and that
the popup's own Confirm arriving after the dismissal still resolves exactly once rather than
skipping the Transaction behind it. Every dismissal in it is followed by the next
Transaction still being shown — a check that proved a popup which never came back would be
asserting the one failure this app exists to prevent.

**ninth**, which shipped twice and is the reason `Invoke-PinnedRequest` exists: 5.1's
`Invoke-WebRequest` and `Invoke-RestMethod` have **no `-SkipCertificateCheck`** (PS 6+
only) and no way to pin, so neither can reach an `https` endpoint whose certificate is
not chain-trusted on the machine making the call — which is every `-SelfSigned`
install here, `New-SelfSignedCertificate` writing to `Cert:\LocalMachine\My` and
nothing putting a copy in `LocalMachine\Root`. The failure is *"Could not establish
trust relationship for the SSL/TLS secure channel"*, and both call sites swallowed it:
`install-iis.ps1` warned that a healthy server had not answered, `update.ps1` rolled a
good update back (#109). The scriptblock form of
`ServerCertificateValidationCallback` is not the way out either — trap four's cousin,
it throws "There is no Runspace available" off a thread with no runspace. Set a
**compiled** callback on the request, which is what that helper does.

Beside it, the other half of that queue: **backing out of a rejection**. The real popup and the real reason dialog again, since what is asked is which window is on screen and whether the queue still moves, and both exits are driven rather than the one that was broken - the X passed either way, and a pair one half of which cannot fail is a restatement rather than a measurement. Each leg asserts that the dialog goes, that the popup comes back still asking, and that nothing was rejected and nothing advanced. The positive half is going through with it: the rejection reaches the app exactly once, the popup closes, and the Transaction behind it is still shown - so the group cannot pass by finding a dialog that never rejects anything.

One group is an **absence** rather than a window: every exit from `notifier_app.py` is `_quit`. That function is two halves, and only the second — stopping the poll loop, the tray icon and the mainloop — is the one somebody reaching for an exit writes out by hand; the first is `app.stopped` and the ship of whatever `client.log` still holds, and it is what went missing when the forced update's Download & Install Now did exactly that. So `self.running = False`, `self.tray_icon.stop()` and `self.root.quit`/`destroy` may appear in that file only inside `_quit`, found by the function each node is written in rather than by a text sweep, since `self.root.destroy` handed to `after()` is not a call at all. A **source** check because it claims an absence, and because the one place it was wrong is a Tk callback needing a server that advertises a version it holds no zip for and five postponements before it can be clicked. The **Storekeeper is deliberately not held to it** — a bare `root.destroy()` is covered there by the `app.stopped` and `ship_log` after `root.mainloop()` returns — and that pair is asserted in the same group, so the scoping cannot go on being right for a reason that has stopped holding.

One group is about none of that but about what a client leaves on disk: the applier keeping **one** `update_rollback\` generation. Three successive updates are driven against a real install directory and a real zip, with only the three things that leave the machine or take a minute stubbed - the wait on the app's process, the relaunch and the health check - because the count is a property of what several runs leave behind and nothing static can see it. The two halves either side of the count are what make it a measurement: the generation that is kept has to hold the build that was just replaced, since clearing the wrong one would pass a count of one while throwing away the only copy that can be restored; and a start that never comes up still has to roll back, which is the property the deletion is placed before the install moves in order to protect.

Two groups beside it are the two halves of **what an update says about itself** (#148), and they are split the way the feature is. The first drives the applier three times over the same install directory, with the same three stubs - the wait on the app's process, the relaunch, the health check - and asserts the `update_result.json` each run leaves: an update that worked is `applied` carrying both versions and the **real digest of the zip**, one whose app never came up is `rolled_back` with a reason beside it, and one where the app never stopped is `failed` with the install still on the build it was on. All three, because the outcome that is easy to get right is the one that worked, and a rollback reported as an update is an Admin reading a green System Log over a fleet stuck on an old build. The second drives `common.report_update_result` against a hand-written file and reads **both halves of the log** back, as every other client entry here is read: the event name, the level, that the detail carries both versions and the digest, that an ordinary start ships nothing, and that an outcome this build does not know is cleared rather than read again for ever. What is worth driving there is the **deletion**: the file goes once the entry is queued and **stays** when `log_event` answers False, which is the only thing that keeps an outcome from being lost to a log write or reported twice.

One group beside them is the **pushed** update (#177), which is the same path with nobody in front of it: an Admin queues `update_now` from Connected Clients and the Client obeys it on its next check-in, so the three answers the click path puts to the engineer have to be decided by the client on its own. Both apps' handlers are driven - the Notifier's through `_commands()`, the Storekeeper's `_update_now` against a stubbed `/version` - and what is asserted is which of the three each picks: already on the published version applies **nothing** and says so at `info`, a server holding no package for this app applies nothing and says so at `warn` rather than opening a browser at the installer, which is what the click path does and is exactly what an unattended push must not do, and only a machine that is behind applies anything. `_queue_command` refuses the middle one at issue time, but a week may pass before the command is collected, so it is the client's to answer again. Beside them the two absences: an answer that applied nothing leaves `update_state.json` exactly as it found it, that file being the **engineer's** postpone count against a version they were asked about where nobody was asked here, and a push arriving while an update is already running starts no second applier - driven through the real `_apply_source_update` with the flag already set, the guard being its own. That the Storekeeper's `obey()` hands the command to that handler at all is a **source** check, its handler map being built inline in the 15s tick against a server this file deliberately does not have.

All eleven **PowerShell** scripts are **pure ASCII on purpose** (`_devtools.py`, `cascade-audit.py`, `server-checks.py` and `client-checks.py` are Python and not subject to this): Windows PowerShell 5.1 reads a BOM-less file as cp1252, where an em-dash's trailing byte becomes a smart quote and breaks parsing. Several PowerShell traps worth remembering, the first three of which shipped as bugs here first: `Sort-Object -Unique` over identical values returns a bare string, whose `[0]` is its first character rather than the whole value — wrap it in `@()`; a parameter may not be named after a common-parameter alias, so the database path is `-DbPath`, never `-Db` (that is `-Debug`); and a `[switch]` parameter on a **function** is bound by name only, so it is skipped during positional binding — `Resolve-Switch "SelfSigned" $SelfSigned` bound the value to the *next* parameter and silently returned false for a config that said true, which is why `Resolve-Switch` takes a `[bool]`. A fourth, which cost real debugging time in a test harness rather than in shipped code: these scripts report through `Write-Host`, which writes to the **information** stream, so `& script 2>&1` captures none of it and every assertion against the output silently fails — capture with `*>&1` (inside PowerShell only — in a bash shell `*` globs the working directory into the argument list, so use `2>&1` there). A fifth, from the same harness: `-match` against an **array** filters it and does **not** populate `$Matches`, so a capture group has to be taken from a scalar — select the line first. A **sixth and seventh**, both edition-dependent and both of which shipped here: `Set-Content -Encoding UTF8` writes a **BOM** under Windows PowerShell 5.1 (`utf8NoBOM` exists only in PS 6+), and every Python app here reads its config with a plain `open()`/`json.load`, which decodes that BOM as cp1252 and dies on `Expecting value: line 1 column 1 (char 0)` — write JSON through `Write-JsonFile` in `_deploy.ps1`, which wraps `[IO.File]::WriteAllText` with a no-BOM `UTF8Encoding` and resolves the path first because .NET has its own current directory. Six shipped **twice**, three lines apart in `install-iis.ps1`, where `server_config.json` was fixed for it and `iis.json` beside it was not, which is why `install-iis.ps1`'s two JSON writes and `dev-run.ps1`'s five now go through that one helper rather than through call sites a reader could pick the wrong spelling at. **Every JSON write in `tools\` goes through it**, 057 having taken the last three — the `manifest.json` writes in `package.ps1` and `bundle-client.ps1` and `installed.json` in `update.ps1`, none of which was broken, since PowerShell's own `ConvertFrom-Json` eats a BOM without complaining. What is left on `Set-Content -Encoding UTF8` is `web.config` alone, which keeps its BOM on purpose. `cascade-audit.py` still decodes a manifest `utf-8-sig` regardless: fixing a writer rewrites nothing already on disk, and a package built before 057 is still sitting on a build machine with the BOM in it; and 5.1's `ConvertFrom-Json` hands back a JSON **array** as one `Object[]` rather than enumerating it, so `@(...)` wraps it into a single element and a `foreach` over it runs **once** with the loop variable bound to every row at the same time — which is how `dev-run.ps1 -Stop` came to kill every recorded pid at once, defeating its own recycled-pid name check. Pipe through `ForEach-Object { $_ }` to flatten it identically on both editions. An **eighth**, caught in 022's verification rather than shipped, and really one fact about `@`: it is three different things and only one of them is a splat. `@(...)` is an **array subexpression**, so `& py @($flags) file.py` passes the whole list as a single argument - only `@variable` splats at all. And an **array** splat binds **positionally**, never by name: `$a = @("-App", "notifier"); & .\bundle-client.ps1 @a` hands the literal string `-App` to that script's first parameter, where its own `ValidateSet` refuses it and names the flag as the bad value - a message that reads like the callee is broken. Only a **hashtable** splat binds by name, which is what `package.ps1` builds its `bundle-client.ps1` arguments as, with a `[switch]` passed as `$true`. Both shapes were written here in one afternoon, and neither is a syntax error.

### `tools/deploy-checks.ps1`

Behaviour checks for the deployment helpers in `_deploy.ps1` - the fourth gate, run
beside the other three before `package.ps1`, and the only one written in PowerShell,
because what it drives is PowerShell. **No Pester**, for the reason the other three
carry no test framework: a release gate that needs something installed first is one
that stops being run (rule 13). Same shape as those - it exits non-zero, it writes
nothing outside a scratch directory of its own, and it needs no IIS, no elevation and,
by default, no network: the one check that touches one is skipped rather than run
without `-ServerUrl`, which is what keeps gate.py's own no-argument call to this
script true to that.

What it covers is `install-iis.ps1`'s **first-time-setup certificate decision**, and
beside it `update.ps1`'s **install-directory decision**, the **interpreter a source
install's migrations run under**, `bind-cert.ps1`, `bind-port.ps1`, and #242's
deployment half: that
the URL Rewrite refusal replaced the warning and that the rule it writes is still
named `AssetManagerClientAddress` under `system.webServer/rewrite/rules` (source
checks, for the reason every other `install-iis.ps1` decision here is one), and that
`GET /health`'s `seen_from` is the caller's own address rather than the server's -
the one live check in this file, run against `-ServerUrl` from a machine that is not
the server and skipped with none.
Everything the other three gates know about that script is a source fact - that a
replacement warning names two fingerprints, that an https probe goes through
`Invoke-PinnedRequest` - because the script stands up IIS and no gate can run it. A
source check cannot see a boolean written the wrong way round, and this is the decision
there whose wrong answer costs the most: every client pins `ssl_cert.pem` and fails
closed against anything else (rule 1), so a run that regenerated over an existing
certificate strands the whole fleet with nothing said at the time. So the three
conditions are `Test-FirstTimeCertSetup` in `_deploy.ps1` rather than three lines inside
that script, and this drives **all four** states over them with
`Get-BoundCertThumbprint` stubbed and an `InstallDir` staged on disk: nothing on the
machine generates, a pem alone refuses, a binding alone refuses - the leg a single
condition would get wrong - and both refuse. Beside them, that the script asks that
helper and kept no second copy of either condition, and that the generation still sits
inside `ShouldProcess`, so `-WhatIf` mints nothing.

`update.ps1`'s is the same shape for the same reason: that script stops an app pool,
overwrites an install and migrates a database, so no gate can run it either, and
where it takes its install directory from is a decision a source read cannot check.
So it is `Resolve-InstallFromTools` in `_deploy.ps1`, and this drives every state
over it against a `tools\` staged on disk: no install around it answers `$null`,
which is what keeps the refusal for a `tools\` carried to a machine by hand;
`installed.json` answers, and `server_config.json` alone answers too, that being the
never-updated install the ticket was raised from; and a `.git` beside it refuses
whatever the markers say — as a directory and as the file a worktree carries — which
is the leg that would otherwise point an update at a repo. Beside them, that
`update.ps1` asks that helper, hands it its own `$StateFile` rather than a second
spelling of the name, derives nothing of its own from `$PSScriptRoot`, and still
refuses when nothing answered.

`Resolve-ServerRunner` is driven here for the third version of that argument: the
`&` that runs it is in `update.ps1` and `migrate.ps1` rather than in the helper
that picks the name, so neither end reads wrong, and in `update.ps1` it is
reached after the app pool has been stopped and the database copied aside. With
`$env:PATH` narrowed to one directory — so what resolves is this check's decision
and not the machine's — a bare name on it has to come back as a **full path**, a
full path as itself, and a name that resolves to nothing has to **refuse** naming
`pythonExe` rather than hand the name back to be invoked; an exe install has to
be unaffected by an interpreter that is not there, the exe branch answering
before the question is asked. The refusal is reachable at all because this gate
defines the `Fail` that `_deploy.ps1`'s header says a caller must, as a `throw`
rather than the print-and-exit a script gives it.

`bind-cert.ps1` is the other way round and deliberately so: it imports into
`Cert:\LocalMachine\My` and writes `IIS:\SslBindings`, neither of which a gate may
do, and the one decision in it that could be driven is not its own. So what is
asserted is what a source read can see and what costs the most when it is wrong
— that the import and the bind go through `Import-CertPair` and
`Set-SiteCertificate` rather than a second `IIS:\SslBindings` write beside
`update.ps1`'s reconcile, that both fingerprints come from `Get-CertFingerprint`
and none from `Get-FileHash`, that elevation is checked **before** the settings are
resolved, and that it reads `iis.json` and writes no JSON at all.

`bind-port.ps1` is checked the same way and for the same reason — it writes
`IIS:\SslBindings`, adds a firewall rule and restarts an app pool, so there is
nothing in it a gate may run. What is asserted there is the **order**, which is the
whole of what that script is: `New-WebBinding` before `Start-Sleep -Seconds $Grace`
before `Remove-WebBinding`, as three offsets rather than as the presence of each,
because each of them separately was already in `install-iis.ps1` and what is new here
is that the old binding comes down **last**. A reversed pair is every client that had
not recorded `next_port` stranded, with the run reporting success. Beside it: that the
wait is the parameter rather than a literal and its default is still 120 seconds; that
both JSON writes go through `Write-JsonFile` and are **read**-modify-writes — counted
at the start of a line, so the comment naming that helper as where trap six is written
down is a reason and not a write, the same distinction the `IIS:\SslBindings` assert
above it draws; that the certificate carried onto the new port comes from
`Get-BoundCertThumbprint` and never off `ssl_cert.pem`; and that every step sits inside
a `$PSCmdlet.ShouldProcess`, so `-WhatIf` prints all seven and changes nothing.

### `tools/gate.py`

Runs the gates a change actually owes, in parallel, and says which and why.
`py -3.12 tools/gate.py` against the fork point with `main`, `--base <rev>` against
somewhere else, `--all` for every gate and `tools/upgrade-drill.py` beside them - the
one gate no path owes, `RELEASE_ONLY`, so neither a `MAP` row nor an unmapped path's
"everything" runs it - `--list` to name the plan and run nothing,
`-j <n>` for the shard count (default: cores, capped at eight), `-v` to pass `-v` down.

It exists because the four gates cost the same whatever moved. Measured here before it
was written: `cascade-audit.py` 6s, `server-checks.py` 5m47s, `client-checks.py` 3m01s -
nine minutes, serially, on one core, for a change to a Markdown file no Python in the
tree reads, and `land.py` paid it again per land and per merge. A gate that expensive on
a commit that cannot have broken it is a gate people learn to skip, and the ones worth
having get skipped with it.

Two savings, and they compose. **Only the suites the diff can reach**: a docs-only
change owes `cascade-audit.py` and nothing else, which is six seconds. **Shards**:
`server-checks.py` and `client-checks.py` take `--shard i/n`, so eight of the first run
at once for 2m40s instead of 5m47s and four of the second for 2m00s instead of 3m01s -
well under linear, most of both suites being Tk building real windows, which Windows
serialises more of than it looks.

**The shard count is capped per suite, and the cap is measured.**
`client-checks.py`'s two popup groups (#194, #201) drive real `after` timers with the
numbers turned down to the smallest thing a wall clock can show - deliberately, their
docstrings arguing that reaching past the timer would pass against a popup whose timer
was never armed - and eight shards on twelve cores takes that margin away and fails both
of them. Four does not: green twice, with the assertion counts summing to what a serial
run makes. Those checks have sat in `tools/client_checks/popup.py` since #238, which
moved nothing the cap is against: it is on how many shards run at once, and `--shard`
still slices every group by position. That summing is the check that matters when the
cap is next moved, not the colour - a shard that silently ran fewer groups would be green too. The total to sum
against is the serial run of the day rather than a number read off this page: it was 872
when the cap was set and is 928 now.
`server-checks.py` has no cap: #214 measured it after a report of the narrow-band group
(the 1.75x/940px leg of `nothing on this window is cut off at a narrow size`) flaking
under 8 shards, and three `--all -j 8` runs plus three `--all -j 4` runs all came back
GREEN, the narrow-band leg passing every time, with the assertion counts summing to the
serial total of the day (2615 then, 2703 now) - nothing measured to cap.

**#214's result no longer reproduces**, and the two failures behind that have different
causes. Re-measured 2026-09-22 over two 8-shard runs of `server-checks.py` by hand, both
red, a different shard each time:

- `tls.py`'s `a quiet tick paints nothing`, whose banner never went green over a port that
  was answering, failed once and is green run alone with `AM_GATE_OFFSCREEN=1`. That one
  is load, which is the thing a cap addresses. It was never diagnosed further and is its
  own ticket if it recurs.
- The narrow-band leg #214 was called on (1.75x at 940px) was **neither load nor the
  offscreen flag**, and was not a sharding question at all. `resize()` ended on two
  identical reads, which is a knife edge: a half-settled band reads a few pixels short and
  then agrees with itself once before the children finish. A third identical read costs
  one 60ms pass and makes the leg repeatable. Fixed under #239; the matrix of runs that
  produced the wrong first reading is kept in `../tickets/064-the-narrow-band-leg-settled-on-two-identical-reads.md`.

So one of those two argues for a cap and the other turned out not to be about shards. The
suite stays uncapped on that: one load failure is thinner evidence than the wall clock a
cap costs on every run.

The map is **per file, not per check group**. A group's dependencies would be a second
list to keep, and the first row of it to go stale would be the one excusing a suite that
should have run. `server.py` and `migrations/` reach the server suite; the three client
apps, `applaunch.py`, `client_update.py` and the `run_*` launchers reach the client one;
`common.py` and `ui_kit.py` reach both, since `server-checks.py` stages `common.py` for
the password door and the certificate bootstrap and measures the Server GUI's
`ui_kit.fit` callers; `ui_kit.py` also reaches `palette-contrast.py`'s gate (073), the
one the other two do not need since neither touches `DARK` or `LIGHT`;
`tools/_offscreen.py` reaches both as well, both suites importing
it and calling it from `main()`; `tools/*.ps1` reaches `deploy-checks.ps1`; prose reaches
nothing.
`cascade-audit.py` always runs whatever changed - it is the cheap one, it is the one a
documentation change is *about*, and the cascade lands before the gate run rather than
after it.

**A path the map does not know runs every gate and says so.** That is the negative half,
and the whole reason this is safe to put in front of `land.py`: adding a file to the repo
cannot quietly subtract a gate, it can only cost a full run until somebody maps it. Add
the row in `gate.py` and describe it here in the same change.

It sets the environment the suites want: `PYTHONIOENCODING=utf-8` for all three Python
gates, and `AM_GATE_OFFSCREEN=1`, which is `tools/_offscreen.py` below. A suite run by
hand does not get that second one, on purpose.

**It drops one known-noise traceback rather than printing it as a finding.** A Tk
`Variable` collected after `mainloop()` has returned tries to unset itself in Tcl and
finds the interpreter gone, so `Variable.__del__` raises into `sys.unraisablehook` at
interpreter exit on an otherwise green `server-checks.py` run - #214 measured the block
as always five lines under `Traceback (most recent call last):`, always ending either
`RuntimeError: main thread is not in main loop` or naming the `refresh_stats` `after`
callback's stale Tcl command. `report()` recognises only that terminal line and drops
the block; any other traceback still prints. Fixing the underlying leak in
`server-checks.py` is a separate change.

### `tools/_offscreen.py`

Opens the window suites' Tk windows where they cannot take the screen or the keyboard.
Imported by `server-checks.py` and `client-checks.py`, which call `enable_if_asked()`
first thing in `main()`; it does nothing unless `AM_GATE_OFFSCREEN=1` is set, which
`gate.py` sets and a direct run of either suite does not.

It exists because the windows cannot simply be hidden. Both suites measure real mapped
windows - a withdrawn Tk window reports 1x1 at its parent's last position, which is why
`client-checks.py` calls `deiconify` in four places deliberately - so for the nine
minutes a full serial run took, forty-one roots plus every window the apps under test
open were the developer's screen, and `focus_force` at four sites plus every
`ui_kit.raise_open` took the keyboard out of whatever else was being typed.

Two patches, both on `tkinter` itself rather than on the 41 `tk.Tk()` call sites, since
the windows that matter are opened by the apps under test and not by the suites at all.
**Translated**: every window is placed `OFFSET` px right of the desktop and `wm_geometry`
rewrites the position half of whatever an app asks for after that, passing the size half
through untouched. That is safe because no check in either suite reads an absolute
position - every `winfo_rootx`/`winfo_rooty` use is a difference between a child and its
own window, and a translation cancels in a difference - and because neither suite
captures screen pixels, so a window nothing composites costs nothing. **Disabled**:
`-disabled` is `WS_DISABLED`, so the window cannot be activated and cannot take focus.
Offscreen alone does not do that, and an invisible window holding the keyboard is the
worse half of the problem rather than the smaller one. Tk's `event_generate` puts events
into Tk's own queue rather than through Windows, so the synthetic clicks and keystrokes
both suites drive still land.

**The check on it is the assertion counts, not the colour.** A synthetic event that
stopped being delivered would take its assertions with it and still print green. Both
suites come back the same either side of the module. Re-measured 2026-09-22:
`client-checks.py` is 928 assertions in 69 groups serial with it off and the same 928
in 69 summed over four shards with it on; `server-checks.py` is 2626 in 236 serial
either way - serial rather than sharded on that side because eight shards of it came
back red twice the same afternoon on load, which is the paragraph above. The earlier
measurement was 872 in 68 and 2615 in 234; both suites have grown since. Re-measure
that way if
either patch is touched.

### `tools/palette-contrast.py`

The fifth gate (073): holds `ui_kit.DARK` and `ui_kit.LIGHT` to a 4.5:1 contrast
floor, which nothing else in the file measures - `ui_kit._check()` holds distances
between tokens, and none of them is a ratio. `py -3.12 tools\palette-contrast.py`,
`-v` for every pair rather than only a failure.

Walks `{TEXT, SUBTEXT, FAINT, WARNING, SUCCESS, DANGER} x {CARD, BG, INPUT_BG}`
against both palettes - the text hierarchy and the direction colours over the three
flat surfaces, which is what pass 3's own table (`prototypes/NOTES-3.md`) names and
nothing else in `ui_kit.py`'s `TOKENS` is. `ratio()` is `pass3_ui.py`'s WCAG
relative-luminance formula, copied rather than imported: `prototypes/` is unmapped in
`gate.py`'s `MAP` on purpose, a throwaway prototype this script has to outlive.

Not sharded and not in `SHARDABLE` - it imports two dicts and does arithmetic, there
is no window to open and nothing a wall clock would notice splitting eight ways.
Reached from `tools/gate.py`'s `MAP` two ways: the shared
`ui_kit.py`/`common.py` row, and its own row, the same reason `tools/_offscreen.py` above has
one - an edit to the checker re-runs the checker.

Measured at commit: dark's worst pair is `FAINT` on `CARD` at 4.63, light's is
`FAINT` on `BG` at 4.78, both against the 4.5 floor.

### `tools/land.py`

Lands a finished branch: checks it, runs `gate.py --all`, merges it into
local `main`, pushes and cleans up. `py -3.12 tools/land.py`, with `--dry-run`
saying what it would do and changing nothing.

**It refuses rather than guesses**, which is the whole of it: a dirty tree, a
conflict with `main`, a `main` held by another worktree, or a red suite each
stop it before anything is published, and it says what it found instead of
working around it. The interpreter is asked for as `py -3.12` by name for rule
13's reason - the gates import the apps, and the vendored `lib\` is pinned
to one Python minor version. It ran the two Python suites directly and serially until
`gate.py` arrived; going through `gate.py --all` is nine minutes down to about five and
adds the two gates a land was not running at all, `cascade-audit.py` and
`deploy-checks.ps1`.

**Committing is deliberately not its job.** A commit carries a message somebody
chose, and a script that stages whatever it finds will eventually sweep another
session's half-written file into `main` - which in a repo worked in several
worktrees at once is not a hypothetical. Commit first, land second.

The ticket number is the trailing `-123` of the branch name and nothing else:
`claude/happy-swirles-cc0d96` parses to none and the issue is left alone rather
than guessed at, a hex suffix not being a ticket.

### `tools/upgrade-drill.py`

Proves upgrade, downgrade and a client rollback against the previous release, the way
it was proved by hand on 2026-09-23 (#274). `py -3.12 tools/upgrade-drill.py` finds the
previous release as the newest `v*` tag below `APP_VERSION`; `--from <ref>` names any
commit instead, and `-v` prints every passing line. **`gate.py --all` runs it and a
normal `gate.py` does not**: it packages two releases and takes minutes whatever the
diff, and it proves a release rather than a change.

It exists because two automated attempts before it reported a pass without having run
the path at all - one read schema 4 when the real schema was 15, one never started a
client. Everything it compares is read off a database or a file the run wrote. In a
temporary directory it removes afterwards:

1. **Packages the old tree with its own `package.ps1`**, from a detached worktree of the
   ref, and this tree with this one. The current script cannot package an older tree -
   its `$SourceFiles` names modules the old tree does not have - and script and source
   coming from one commit is the design. Both runs are handed the same `lib-server\` and
   `lib-client\`, this checkout's or else the main checkout's, a worktree carrying none.
2. **Installs the old server package and seeds it over HTTP**: `run_server.py serve`
   with `HTTP_PLATFORM_PORT` on a free loopback port, two members, three transactions,
   one confirmed and one rejected. Assets come from the install's own `assets` table, and
   each seeding round takes ones no earlier round moved - a second pending move of the
   same asset is a 409.
3. **Records** `PRAGMA user_version`, `integrity_check`, `foreign_key_check`, the
   per-table counts and every transaction and member row.
   `user_version` is printed here rather than asserted: a fresh install before #275
   was never stamped, so 2.5.1 reads 0 until its first update. Steps 4 and 5 assert it.
4. **Upgrades with the new package's `update.ps1`**, starts the new build and seeds it
   again: schema at the package's `schema_version`, every row from 3 unchanged field for
   field. There is no service here, so `update.ps1` stops nothing and reports that the
   host did not start; the drill runs it with `-SkipHealth` and starts the host itself.
5. **Downgrades with the old package's `update.ps1`**: schema back at the old version,
   and every row from 3 and 4 still there, field for field. Fields the old row had
   only - a column the upgrade added is the migration's to drop.
6. **Updates a `StorekeeperApp` install** from the old `<App>-<version>.zip` to the new
   one with the installed `client_update.py --apply`, and hash-compares every file against
   the new manifest. Then a second old install is handed the new zip with a launcher
   that exits at once, and the rollback must leave every old file byte-identical. **Each
   zip is copied into a `mkdtemp` folder of its own** first: `apply_update` removes the
   zip's parent folder on success in the older builds.

Python is pinned with `py -3.12` throughout, and put first on `PATH` for `package.ps1`,
which calls a bare `python`: a bare `py` picks up 3.14, and rule 13's check correctly
refuses to start. **Every process started is killed before the folder goes**, matched
on the temp folder's name in its command line - the relaunched clients are detached and
cannot be waited on, and a live one holds files the removal would trip over. It prints
failures and a last line, and exits 1 on any failure, a package that will not build
included.

### `tools/CLAUDE.md`

The working instructions for an agent editing this directory - read before
writing, skip a file over 100KB unless it is needed, no guessed APIs, flags,
versions or commit SHAs. It is documentation rather than a script and runs
nothing; it is named here because `cascade-audit.py` holds **every** file in
`tools\` to having a row in this reference, which is what stops a script
arriving with nothing anywhere saying what it is for.

Back to [CLAUDE.md](../../CLAUDE.md).
