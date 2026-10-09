# 001 - package.ps1 generates a self-signed certificate and ships it with the server package

**Type:** enhancement · **Depends on:** nothing

## What is asked

`tools/package.ps1` should create a self-signed certificate itself and include it in the
server package, instead of only resolving one that already exists.

## Where it stands today

`package.ps1` resolves `ssl_cert.pem` from three sources in order - `-CertPath` /
`certPath`, then `<installDir>\ssl_cert.pem` from `deploy.json`, then `GET <baseUrl>/cert`
- and **fails** when none of them answers, naming `install-iis.ps1 -SelfSigned` as what
produces one and `-NoCert` as the deliberate plain-HTTP path. It refuses any file holding
a `PRIVATE KEY`. See `tools/package.ps1` lines ~266-370 and the `package.ps1` section of
`CLAUDE.md`.

## The conflict this ticket resolves

Both `CLAUDE.md` and `package.ps1`'s own header say it **never generates a certificate**,
for a stated reason: the private key would be on the build machine and not on the machine
IIS binds, so every client that pinned the shipped public half would be permanently unable
to reach the server, with no verified channel left to correct it over (rule 1, ADR-0010).

Generating one is fine only if the private key can reach the server. **Shape A is the one
chosen** (the alternative, leaving generation to `install-iis.ps1 -SelfSigned`, is what
happens today and would be a docs change only):

> `package.ps1 -SelfSigned` mints the pair when no certificate resolves, stages the public
> half in the package, writes the private half **beside** the package and never inside it,
> and prints the SHA-256 fingerprint. `install-iis.ps1` binds the pair on the target
> machine.

## Scope

- A `-SelfSigned` switch on `tools/package.ps1`. Without it, today's three-source
  resolution and its failure message are unchanged.
- Generation goes through `tools/_devtools.py cert` rather than a second copy of the
  X.509 logic - it already writes `CA:TRUE`, an IPAddress SAN and DNS SANs, each of which
  fails silently if omitted (see the `_devtools.py` section of `CLAUDE.md`). Extend it with
  the hostname/IP it should carry rather than hardcoding the dev-run 127.0.0.1 values; the
  server's are `asset-server` / `192.0.2.100`.
- The staged-file private-key refusal stays exactly as it is. The generated `ssl_key.pem`
  is written next to the zip, never staged.
- Print the fingerprint of what was generated, the way the `GET /cert` path already does.
- The script is **pure ASCII** - Windows PowerShell 5.1 reads a BOM-less file as cp1252.

## Cascade

- The `tools/package.ps1` section of `CLAUDE.md`: the "It never generates a certificate"
  sentence and the reason beside it have to change to say when it does.
- `tools/_devtools.py`'s section in `CLAUDE.md` if `cert` grows arguments.
- `docs/runbooks/iis-cutover.md` - check the certificate step still reads true.
- ADR-0010 names where a client's certificate comes from; check that sentence still holds.
- Run `python tools/cascade-audit.py` - it checks every `tools/*.ps1` against its section.
