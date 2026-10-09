---
status: accepted
---

# The console moves the binding through an elevated half

Under IIS (ADR-0001) the server runs as the app pool identity. That account is
not an administrator: it cannot write `IIS:\SslBindings`, cannot add or remove
a site binding, cannot create a firewall rule and cannot restart its own app
pool. Everything that IIS actually serves this install on is therefore outside
the reach of the process being served, and the console is that process.

Two of the console's actions are about exactly those things. The certificate
cutover replaces `ssl_cert.pem` in process and then has to put the new
certificate on the site's https port; Change Host / Port writes a number into
`server_config.json` and then has to move the site off one port and onto
another. Neither can finish what it starts.

ADR-0020 answered that for the certificate, in one sentence buried in a
decision about rotation phases: the console spawns `tools\bind-cert.ps1`
elevated, says plainly that the files are in place and the binding has not
moved yet, and prints the exact command when the elevation is refused. 069
needed the same answer for the port, which is what makes it a shape rather
than a detail of certificates.

## Decision

**An act the app pool identity cannot perform is a script under `tools\` that
the console spawns elevated, never something the console asks an operator to
go and run by hand.**

Four things follow from it, and all four are what `bind-cert.ps1` already did:

- **The command is built in one place, in Python, and that place is
  `server_iis.py`.** `_bind_cert_command` and `_bind_port_command` return the
  argument list; the window spawns that list and, when the elevation is
  refused, prints that same list. Two spellings of one command is how somebody
  ends up pasting a line that does nothing and reporting that the act did not
  work.
- **The script does the one act and nothing else.** `install-iis.ps1` would
  bind a certificate and would move a port, and would also create the site and
  the app pool, rewrite `web.config`, re-grant ACLs and ask questions on an
  interactive run. A full install is not a way to change one thing.
- **A refused elevation is an ordinary answer, not a failure.** By the time the
  prompt appears, the in-process half has already happened - the files are
  swapped, the number is saved - so what is owed is the exact command rather
  than an apology, and the console says which half did not happen.
- **The System Log entry is written before the spawn.** What follows is a
  restart or an app pool recycle, and an entry written after one goes missing.

## The port's own half

`tools\bind-port.ps1` is that script for the port, and it differs from
`bind-cert.ps1` in two ways that are the ticket rather than the pattern.

**It has a grace window.** A certificate cutover is instantaneous by nature:
one certificate is presented or the other is. A port move need not be, and must
not be. While the old binding is still answering, `/health` on the old port
advertises the saved number as `next_port`, and every online client records it
on its 15s tick and falls back to it - then to `last_known_port` - when the old
port dies. So the script binds the new port **beside** the old one, waits
`-Grace` seconds (120 by default, eight client ticks), and only then removes the
old binding. A move that took the old port away first would strand every client
that had not been told, which is the failure ADR-0020 is written around.

**It writes `iis.json`.** `bind-cert.ps1` deliberately does not: that file is
`install-iis.ps1`'s record of what it bound, and which certificate is on the
port is not among the facts it records. The **port** is among them, so a script
that moves the binding and left that key alone would leave the record naming a
port nothing serves - and that record is what `update.ps1` and the Server GUI's
banner both take at its word. It read-modify-writes, for the reason every
writer of `server_config.json` does.

## Consequences

- **`install-iis.ps1` is no longer the only thing that moves the port.** Its
  own `-Port` still does, as part of a full install; ADR-0001's consequence
  naming it as *the* way is corrected, and the Server GUI no longer sends the
  Admin off to run it by hand.
- **`server_config.json` has a third writer outside the server**, beside
  `install-iis.ps1` and `installer.py`. All three read-modify-write, touch
  `port` alone, leave an unreadable file alone rather than replacing it, and
  write no-BOM UTF-8 - which is what keeps that file safe to have three writers
  of (ADR-0013).
- **`POST /admin/server_config` does not spawn.** It runs as the app pool
  identity and cannot, so under IIS it answers that the binding moves when the
  console applies it. A delegate with the Change Host / Port capability
  password can still save the number remotely; somebody at the console still
  applies it. That is the same split rule 7 keeps for the admin password and
  ADR-0015 for the remote channel: what is delegable is the setting, not the
  act on the machine.
- **One System Log entry, `server.port_moved`, at `warn`**, naming both ports
  and written before the spawn. `warn` rather than `info` because a client
  switched off through the grace window has to have its `config.json` corrected
  by hand.
- **070 is the third act on this shape** - a certificate installed or removed
  under IIS moves the binding or refuses - and it is written against this ADR
  rather than against ADR-0020.

## What was rejected

**Locking the port field under IIS.** The number in `server_config.json` is
what the console probes for and what the process reads as `PORT`, so a field
that cannot be changed is an install whose two halves can never be brought back
into agreement after a hand-run `install-iis.ps1 -Port`.

**Moving the binding from the route.** `POST /admin/server_config` is reachable
over the network with a capability password, and the app pool identity cannot
bind anything, so the route would have had to spawn something with an
elevation prompt on a machine nobody is standing at. An act needing a person at
the console belongs at the console.

**No grace window - move the binding and let clients recover.** They mostly
would: `last_known_port` is the second fallback and exists for this. But it is
the fallback for a move nobody could announce, and here the announcement is
free - the old listener is up, `/health` already carries `next_port`, and the
only cost is waiting two minutes.
