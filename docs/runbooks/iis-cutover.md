# Runbook — move the API onto IIS

Moves the Asset Server from running as the `AssetManagerServer` service (or from
an interactive GUI session) to running under IIS via HttpPlatformHandler. See
[ADR-0001](../adr/0001-host-api-on-iis-via-httpplatformhandler.md) for why.

Run this **on `asset-server`**, in an elevated PowerShell, during a quiet
window. Clients survive a short outage — the Notifier retries every 15s and the
Storekeeper buffers submissions to `pending_buffer.json` — but a transaction
submitted mid-cutover will sit in that buffer until the server answers again.

The whole cutover is one script. Everything below is the surrounding checks.

---

## Before you start

- [ ] **Fill in `deploy.json`** -- optional for this step now, still worth
      doing. Copy `tools/deploy.example.json` to `tools/deploy.json` on this
      machine and set `installDir`, `port` and the certificate names.
      `install-iis.ps1` asks for the install directory, port, site name and pool
      name when a human runs it — and the certificate names too on a
      `-SelfSigned` run — offering whatever it resolved as each default,
      so a missing file no longer stops the cutover. Fill it in anyway:
      `update.ps1`, `migrate.ps1` and `package.ps1` read the same file, so this
      machine's `installDir` and `baseUrl` are set once here. Every later
      update is `.\tools\update.ps1 -Version <v>` with this file or without
      it -- that updater is installed to `<installDir>\tools\` by the package
      and takes the install directory from its own location where nothing else
      named one -- so what the file still buys there is `baseUrl`, and with no
      `baseUrl` from either source there is no health check and no
      auto-rollback. Of those
      three only `update.ps1` ever asks anything, and only for one thing: when
      the directory it looked in does not hold the version, it says what was
      there and asks where the package is. It reads packages from **one**
      place, `dist\` under `installDir`, so copy a release into
      `<installDir>\dist\<version>\` and there is nothing to configure;
      `-PackageDir` names somewhere else for a one-off -- the directory
      holding the zip, or the zip itself, a file there being read as
      `-Package` rather than searched beneath. That directory is
      looked at twice, `<dir>\<version>\` before `<dir>` itself, since
      `package.ps1` writes `dist\<version>\` and that whole directory is what
      gets carried here, while a zip carried on its own lands beside it; the
      run names which answered. `distDir` here is
      `package.ps1`'s ship root on a **build** machine and is not read by
      `update.ps1` any more — it says so by name if this file still sets it.
      Every switch below can also be passed
      on the command line, where it wins over the file and is not asked about;
      the file exists so the cutover is not a long command retyped from a
      runbook. It is gitignored -- the copy on `asset-server` is the one that
      matters.
- [ ] **Pick the IIS port.** Any port in 1–65535; `install-iis.ps1` refuses
      anything outside that range. 443 was blocked on this network until
      2026-09-12 and is an ordinary port now. If you keep 8081, nothing on
      the client side changes at all. If you pick a different port, read
      *Changing the port* below first.
- [ ] **Decide where the certificate comes from**, one of:
      - **nothing at all, on a first-time setup.** Where no source is given,
        `InstallDir` holds no `ssl_cert.pem` and the site has nothing bound,
        the script generates one exactly as `-SelfSigned` does and says so,
        naming the fingerprint — there is nothing on a fresh machine to point
        it at, so the demand had no answer. Any of those three failing leaves
        the old refusal (*Give a certificate source*) standing, because an
        existing certificate is never regenerated: see *Changing to a different
        certificate strands every client* below. `-WhatIf` generates nothing
        and prints what it would have made.
      - `-SelfSigned` — the script generates one. This is the normal choice
        here: the clients pin `ssl_cert.pem` rather than trusting a CA, so a
        real certificate buys nothing and needs IT. The generated certificate
        carries `CA:TRUE` and both DNS and IP SANs, which are not optional —
        each client loads it as its own trust anchor (OpenSSL 3 rejects a
        non-CA anchor) and urllib3 asserts the SAN even with hostname checking
        off. The names default to this machine's own identity — its computer
        name, its FQDN where it has a domain suffix, `localhost`, and its own
        IPv4 — and an interactive run asks for them with that as the default,
        so read the line it offers before pressing Enter: every name or address
        a client might have in its `server_url` has to be in that list, and a
        name that is not is a client that fails closed. `certDnsNames` /
        `certIpAddress` in `deploy.json`, or `-CertDnsNames` / `-CertIpAddress`
        on the command line, override it. Where no IPv4 can be determined no
        `IPAddress` SAN is written at all — an absent one costs a client
        configured by address, a wrong one costs every client.
      - a thumbprint already in `LocalMachine\My` → `-CertThumbprint AB12...`
      - a `.pfx` file → `-PfxPath C:\certs\sd.pfx`. The script prompts for its
        password interactively; it is never a parameter, so it cannot end up in
        console history or a transcript.
- [ ] **Confirm HttpPlatformHandler is installed.** The script checks and stops
      if it is missing. Install it from the Microsoft download, then rerun.
- [ ] **Confirm URL Rewrite is installed.** Required, not optional (#242): the
      script checks and stops if it is missing, the same as HttpPlatformHandler
      above. Without it `_client_addr()` never sees anything but the loopback
      hop HttpPlatformHandler proxies every request through, so Connected
      Clients and the System Log record `127.0.0.1` for every client rather
      than where it actually came from. Install it from the Microsoft download,
      then rerun.
- [ ] **Back up the database.** `update.ps1` and `migrate.ps1` do this for
      you; this cutover does not touch the database, but it is one copy.
      Check `db_path` in `<InstallDir>\server_config.json` first — the
      database is only `<InstallDir>\assets.db` when nothing overrides it.
- [ ] **Note what is serving right now** — `sc.exe query AssetManagerServer`,
      and whether anyone has the GUI open. Both must stop: two processes cannot
      bind the same port, and the GUI's single-instance probe will keep it in
      monitor-only mode once IIS owns the port. Note it because afterwards
      neither is the control any more: `Start-WebAppPool` / `Stop-WebAppPool
      -Name <pool>` is, and `sc.exe start AssetManagerServer` is refused by the
      SCM as disabled. Once `iis.json` is written the Server GUI names that
      pool, rather than going on offering to stop a server it cannot stop.

---

## Cutover

Dry run first. `-WhatIf` prints every change without making one:

```bash
.\tools\install-iis.ps1 -SelfSigned -WhatIf
```

`-WhatIf` asks nothing -- not the four settings, and not a `-PfxPath`'s password,
since nothing is imported on a rehearsal. So it cannot end up blocked waiting for
an answer. It does still need an elevated shell, and it reports a missing
`installDir` or `port` rather than asking for one.

Then for real:

```bash
.\tools\install-iis.ps1 -SelfSigned
```

With no `deploy.json` the script asks for the install directory, port, site
name and pool name, showing what it resolved as each default; Enter accepts. To
skip the questions, or to override the file, pass them instead:

```bash
.\tools\install-iis.ps1 -InstallDir C:\AssetManager -Port 8081 -CertThumbprint AB12CD34...
```

What it does, in order: resolve settings (command line over `deploy.json`) →
check elevation → ask for the install directory, port, site and pool names,
unless they came from the command line or there is nobody to ask →
preflight (port, the payload present, IIS module, HttpPlatformHandler, URL Rewrite) →
resolve or generate the certificate → write its public half to
`InstallDir\ssl_cert.pem` → **stop and disable the `AssetManagerServer`
service** → write `web.config` pointing at whichever payload `InstallDir`
holds - `python.exe "<InstallDir>\run_server.py" serve` for a source install,
which is every install built since 061, or `AssetServer.exe serve` for one
made before it → create the app pool (no managed runtime, no idle timeout,
no periodic recycle, `AlwaysRunning`) → create the site and its HTTPS
binding → grant the pool identity write access to `InstallDir` (and to the
database's folder when `db_path` puts it outside, since SQLite needs to write
`-wal` and `-shm` beside the file) → add the
firewall rule → write `iis.json` **and record the bound port in
`server_config.json`**, so the GUI and IIS agree on one number → start and probe
`/health`.

The recycling settings are deliberate: the background jobs (24h auto-accept)
need a live process, so an idle timeout would silently stop them.

---

## Verify

```bash
. <InstallDir>\tools\_deploy.ps1
(Invoke-PinnedRequest -Url https://asset-server:8081/health `
                      -PinPath <InstallDir>\ssl_cert.pem).Content
```

`Invoke-RestMethod` cannot answer this on a `-SelfSigned` install and neither
can a browser without a click-through: the certificate is in
`Cert:\LocalMachine\My` and nothing puts a copy in `LocalMachine\Root`, so the
chain is untrusted on the very machine that minted it, and Windows PowerShell
5.1 has no `-SkipCertificateCheck`. `Invoke-PinnedRequest` accepts the
certificate in `ssl_cert.pem` and nothing else, which is the file the clients
pin and `GET /cert` serves — so this checks the same thing they will. It is
what `install-iis.ps1` probes with and what `update.ps1` health-checks with.

- [ ] `/health` answers, and its `port` matches the port you passed.
- [ ] `/version` reports the version you expect — same call, `/version` in place
      of `/health`.
- [ ] The service is gone as a listener: `sc.exe query AssetManagerServer` shows
      `STOPPED`, and its start type is disabled.
- [ ] `iis.json` exists in `InstallDir` and names the app pool — `update.ps1`
      reads it to decide whether to stop a pool or a service.
- [ ] `server_config.json`'s `port` is the same number as the site binding and as
      `iis.json`'s. `server.py` reads `PORT` from that file at import, so while
      the two disagree the Server GUI probes a port IIS does not serve — the
      banner reads OFFLINE over a healthy server, and worse, the GUI finds the
      port it was handed free and starts a second Flask over the same database.
      `install-iis.ps1` writes it now; this checks it landed.
- [ ] Neither `server_config.json` nor `iis.json` starts with a BOM. Both are
      written through `Write-JsonFile` in `_deploy.ps1`, which is trap six's
      answer; this checks the file on disk rather than the writer.

      ```bash
      'iis.json','server_config.json' | ForEach-Object {
          $b = [IO.File]::ReadAllBytes((Join-Path $InstallDir $_))[0..2]
          "$_ : " + ($b -join ' ')
      }
      ```

      `239 187 191` is a BOM. On `server_config.json` that is the checkbox
      above failing silently: `server.py` reads it with a plain `open()` and
      swallows the exception, so the whole file is discarded and `PORT` falls
      back to 8081 while the number you wrote sits there looking correct. On
      `iis.json` nothing breaks - `_iis_host` decodes `utf-8-sig` on purpose,
      for the installs made before the writer was fixed - but a BOM there means
      this run did not go through the helper, and the file beside it did not
      either.
- [ ] Open the Server GUI on the console — `AssetServer.exe` on an exe install,
      `python run_server.py` on a source one: the banner reads `Hosted by IIS`
      and names the site and the app pool, and the tray's Quit offers to close
      the window rather than to stop the server. If it does not, `iis.json` is
      missing or unreadable - the window is then back to claiming this process
      is the server, and so are its Quit and its Server Settings.
- [ ] One engineer's Notifier picks up a pending transaction within 15s.
- [ ] The Storekeeper's history refreshes and its buffer is empty.

---

## Changing the port at the same time

Don't, if you can avoid it — do the cutover on the port clients already use, and
change the port afterwards as its own step. If you must do both:

1. Change the port in the Server GUI (or `POST /admin/server_config`) **while
   the old listener is still up**. `/health` then advertises it as `next_port`,
   and every online client records it within 15s.
2. Then cut over to IIS on that port. Clients whose recorded `next_port` matches
   will find the new listener on their own.

Step 1 is for the **clients** and nothing else — it is what puts the new number
in front of them as `next_port` while there is still a listener to advertise it.
It is not how the server's own `server_config.json` comes to agree with the
binding: `install-iis.ps1` writes the port it bound into that file itself, so
passing `-Port` is enough on that side, and step 1 stays necessary only because a
client that is never told cannot follow.

## Changing the port afterwards

Once IIS is in front of the server the port is the **site binding**, and since
069 the console moves it. This is all `iis.json`'s doing: if IIS was set up by
hand rather than through `install-iis.ps1` and that file was never written,
there is no site on record for `bind-port.ps1` to move. Server Settings and
`POST /admin/server_config` both refuse the port there with a 400 (#267) —
`/health`'s `port_locked` says so — and the fix is to run `install-iis.ps1`,
not to save a number this process cannot apply. Server Settings , **Save** with a new port writes the
number into `server_config.json`, writes one `server.port_moved` entry, and asks
Windows to elevate `tools\bind-port.ps1`, which does seven things in this order:

1. records the port in `server_config.json`;
2. binds the new port **beside** the old one, carrying the certificate the old
   binding is presenting;
3. adds the firewall rule for it, the same rule shape `install-iis.ps1` writes;
4. records the port in `iis.json`;
5. restarts the app pool, so the process re-reads `PORT` and `/health` reports
   the new number (`HTTP_PLATFORM_PORT` is IIS's own loopback port and does not
   change);
6. waits `-Grace` seconds — 120 by default, eight client ticks — with **both**
   ports answering. This is the window: `/health` on the old port advertises the
   new number as `next_port`, and every online client records it;
7. removes the old binding and its `SslBindings` entry, and prints both ports.

Refuse the elevation prompt and nothing has moved except the number in
`server_config.json`; the console prints the exact command to run elevated,
which is the same command it would have run. Run it by hand the same way for an
install whose console nobody is sitting at:

```bash
.\tools\bind-port.ps1 -InstallDir C:\AssetManager -Port 8443
```

`-WhatIf` prints all seven steps and changes nothing. Re-running after an
interrupted move is safe: it finds the new binding already there and still has
the old one to take away. `install-iis.ps1 -Port` still moves the port as part
of a full install — it is the whole install, and it has no grace window.

A client that was switched off through the move still recovers: it tries its
configured port, then `next_port`, then the port it was on before that. A client
switched off for *two* port changes in a row does not, and needs its
`config.json` corrected by hand.

---

## Rollback

`install-iis.ps1` disables the service rather than deleting it, so the way back
is short:

```bash
Stop-WebAppPool AssetManagerPool
Remove-Website AssetManager
Remove-WebAppPool AssetManagerPool
sc.exe config AssetManagerServer start= auto
sc.exe start AssetManagerServer
```

Then delete `iis.json` from `InstallDir`, or `update.ps1` will keep trying to
stop an app pool that no longer exists. Confirm `/health` answers again. With
the file gone, an interactive `update.ps1` asks which site serves this install
rather than assuming one: press Enter, which names the `AssetManagerServer`
service this rollback just put back. A run with nobody at the console stops the
service without asking, as it always did.

Neither this rollback nor `update.ps1`'s own touches the database, and that is
deliberate. `update.ps1` copies it — wherever `db_path` puts it, with its `-wal`
and `-shm` — into `<InstallDir>\rollback\<old-version>\` after it stops the host
and before it migrates, and a failed health check puts the *files* back and
leaves the data alone: the new build was serving while the check ran, and every
transaction recorded in that time is only in the live database. So restoring
that copy, or the migration's own `.bak-v*` beside the database, is a manual
step, taken by someone who has looked at both files and decided which loses
less. Stop the host before you swap anything, and move the `-wal` and `-shm`
with the database or leave neither behind.

---

## Notes

- HTTPS under IIS is terminated by IIS, not by the Flask listener:
  `web.config` runs the server with the `serve` verb, and `HTTP_PLATFORM_PORT`
  makes it bind `127.0.0.1` on a private port with SSL off. `ssl_cert.pem` and
  `ssl_key.pem` next to the server stop being what serves TLS — but keep
  `ssl_cert.pem` there, because `GET /cert` serves it and clients refresh their
  copy from it. The script writes that file for you from whatever certificate
  it bound, backing up any existing copy first.
- **Changing to a different certificate strands every client.** A client
  refreshes `GET /cert` over a connection its current `ssl_cert.pem` has already
  verified, so the moment the server presents an unrelated certificate that
  refresh is exactly what stops working, and the client fails closed rather than
  falling back to the system store. Ship the new `ssl_cert.pem` with
  `AssetManager_Setup.exe` and reinstall, or visit each laptop. Re-running
  `install-iis.ps1` with the same thumbprint is safe; `-SelfSigned` generates a
  **new** certificate every time, so run it once and keep the thumbprint. A
  re-run naming **no** source generates nothing either - that branch is a
  first-time setup only, and an `ssl_cert.pem` or a bound certificate is what
  tells it this is not one.
- **`update.ps1` reconciles a drifted binding instead of only warning about it.**
  `ssl_cert.pem` is the source of truth for what a client pins - it is what `GET /cert`
  serves - so if a later `update.ps1` run's health check finds this site's IIS binding
  presenting a different certificate than `ssl_cert.pem`, it imports this install
  directory's own `ssl_cert.pem`/`ssl_key.pem` into `Cert:\LocalMachine\My` and rebinds
  the site to it, then retries - correcting the binding to match the file rather than the
  reverse, since rebinding to whatever IIS already had would strand every client that has
  already pinned the file. That is one update.ps1 run's own drift; it is not a substitute
  for the reinstall or per-laptop visit above, which is what a genuinely new certificate
  still needs. `-WhatIf` rebinds nothing and only prints both fingerprints, and a server
  with no IIS host at all - the Windows service, or a standalone install - has no binding
  to reconcile, so the mismatch warning stands there exactly as it did before.
- **Rebinding to the certificate `ssl_cert.pem` already names:**
  `tools\bind-cert.ps1` does that one thing and nothing else. It reads the site
  out of `iis.json`, imports this install directory's own
  `ssl_cert.pem`/`ssl_key.pem` into `Cert:\LocalMachine\My` where they are not
  already there, binds the site's https port to that certificate, and prints the
  fingerprint of what was bound before and of what is bound now, then recycles
  the app pool `iis.json` names so the process behind the site re-reads the pair
  it bound at startup. Run it elevated; `-WhatIf` imports nothing, binds nothing
  and recycles nothing. Where no pool is recorded it says so and the recycle is
  yours to do.

  Reach for it rather than re-running `install-iis.ps1`, which is a full site
  install: it creates the site and the app pool, rewrites `web.config`, re-grants
  the ACLs, read-modify-writes `server_config.json` and asks questions on an
  interactive run, none of which is anything to do with swapping a certificate.
  It is also what the Server GUI's own cutover spawns, because under IIS the
  server runs as the app pool identity and cannot rebind in process (ADR-0020).
  It writes no `iis.json` - that file is `install-iis.ps1`'s record of what it
  bound, not an answer typed at one rebind - so if the site was renamed in IIS
  Manager since, pass `-SiteName`. The warning above still holds: a client
  holding the outgoing certificate fails closed against the new one, and this
  script prints both fingerprints so the fleet can be checked against them
  before rather than after.

- **Rotating the certificate without visiting a laptop** is the whole of
  ADR-0020, and it is three steps at the console rather than a script here.
  Server Settings › **Generate** stages `ssl_cert_next.pem`/`ssl_key_next.pem`
  and changes nothing that is served. Connected Clients , **Push Staged
  Certificate** queues `trust_cert` for every installation; each one appends
  the staged certificate to its own `ssl_cert.pem` on its next check-in, so
  it then verifies against either. Server Settings › **Cut over** replaces
  the live pair with the staged one and tells you first how many installations
  have not collected the push - that count comes off the command queue, not off
  the Certificate column, which cannot see an append. Under IIS it then spawns
  `bind-cert.ps1` elevated; refuse the prompt and the files are swapped with the
  binding left where it was, and the exact command to finish it is printed.
  The outgoing pair is in `cert_rollback\` beside the server, one generation only.

- **Hosting a source install instead of the exe?** `install-iis.ps1` detects
  which one `InstallDir` holds and writes `web.config` accordingly, but pass
  `-PythonExe` (or set `pythonExe` in `deploy.json`) rather than relying on
  `python` resolving: the app pool identity has its own environment. Read
  `source-mode.md` first — in particular the note that IIS hosting a source
  install has not been verified yet, so this cutover is where that happens.
- The private key never leaves this machine. Do not put `ssl_key.pem` in a
  release package or next to the installer that goes to engineers.
  `package.ps1` now refuses a certificate that contains a `PRIVATE KEY`
  block — including one it fetched itself — and refuses to stage any file
  named like a key. The build copies no key anywhere any more — `dist\<version>\`
  is what gets handed to whoever installs a client — so a key beside a build is
  something a person put there, and the check is what stands between it and a
  package.
- **`AssetManager_Setup.exe` carries no certificate at all since 061.** A fresh
  client install with none offers the server's SHA-256 fingerprint for
  confirmation on first contact and pins it if the person accepts (ADR-0010),
  so it no longer dead-ends. To spare anyone reading a fingerprint off the
  Server GUI, drop a copy of `<InstallDir>\ssl_cert.pem` next to
  `AssetManager_Setup.exe` — `_ssl_cert_source()` looks there — which is also
  how a renewed certificate goes out without a rebuild.
- **The server package still wants it, best effort.** Copy
  `<InstallDir>\ssl_cert.pem` back to the build machine, or leave `installDir`
  or `baseUrl` in that machine's `deploy.json` and `package.ps1` reads
  `<installDir>\ssl_cert.pem` or fetches `GET <baseUrl>/cert` itself, printing
  the fingerprint to check against the server. It prefers `certPath` when one
  is set, so a stale copy there is still a stale copy shipped, and where none
  of the three answers it warns and packages anyway rather than failing.
- `install-iis.ps1` is pure ASCII on purpose: Windows PowerShell 5.1 reads a
  BOM-less file as cp1252, where an em-dash's trailing byte becomes a smart
  quote and breaks parsing. Keep it that way when editing.
