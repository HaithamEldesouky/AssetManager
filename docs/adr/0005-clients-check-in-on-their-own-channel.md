---
status: accepted
---

# Clients check in on their own channel, not through the heartbeat

`POST /clients/checkin` is a new endpoint. A Client sends the identifier it
generated once and keeps in its own configuration, its hostname, the Windows
account it is running under, which app it is and at what version, and for a
Notifier which Engineer it is configured as. The server adds the source address
it saw the request come from and the time, and answers with the identifier it
recorded, when that installation was first seen, and an empty list of commands.

The obvious cheaper alternative was to widen `GET /health`, which every Client
already calls: hang the facts on the query string, or read them from headers,
and record them as a side effect of the heartbeat nobody would have to add a
call for. That is not what happened, and this is why.

## Why not the heartbeat

**`/health` has to stay answerable with nothing attached.** It is how a Client
finds the server at all, and how the port-change cascade works: a client that
cannot reach its configured port walks the candidates until something answers,
reads `port` and `next_port`, and remembers where it ended up. That has to work
from a client whose configuration is empty, mid-install, or being repaired. A
heartbeat that only records something useful when the caller supplied five
fields is two mechanisms in one endpoint, and the one that matters is the one
that must never grow a precondition.

**The identifying fields must not go in a URL.** A `GET` carries them in the
query string, and under IIS (ADR-0001) HttpPlatformHandler sits behind a
request log that writes the query string verbatim into a file nobody prunes.
That turns an inventory of hostnames and Windows account names into a
by-product of the logging configuration, sitting somewhere nobody decided to
put it. A POST body is not secret either, but it is not written down by default
by a component that has no idea what it is holding.

**The next thing this grows is a response body.** The command queue for a
single Client hands work back through the `commands` field of this response —
that is why the field is here now and always empty, so the queue lands as a
value in a key that was already on the wire. `/health` has a documented
additive-only contract precisely because a stranded client cannot be updated
until it can reach the server; growing it into a two-way channel for a
different purpose spends that contract on something that has its own endpoint
available for free.

So the heartbeat's fields and behaviour are unchanged, and no Client of any
version is affected by this ticket.

## Why it is unauthenticated

For the same reason the Transaction endpoints are — see ADR-0002. A Client
holds no credential, and the one it could be given would ship inside the
package on the laptop it is meant to identify.

What that exposes: somebody who can reach the port can create bogus rows in the
registry, or overwrite a real Client's row by guessing its identifier. That
makes the list untrustworthy as evidence, and it can be made noisy without
limit — the same unbounded-write exposure `POST /transactions` already has, on
a table that is smaller and easier to clear.

What it does not expose: the registry cannot be read back **by anybody who
can write to it**, which is the sentence that matters and is the one that
survived #174. There was no `GET /clients` at all until then - the list is a
map of hostnames, account names and addresses of machines on the internal
network, so the Admin read it at the Server GUI, out of the database rather
than off an endpoint. #174 gives it a route, and what that route is **never**
is open: the admin password, or the **Server Settings** capability password
over HTTPS (ADR-0015), and nothing else. So the asymmetry this section is
about is unchanged - a caller holding no credential may write a row here and
may not read one back - and what changed is where an Admin may stand, not who
may look. `POST /clients/log` beside it is still write-only for the same
reason and with no route of its own at all, the log holding who was refused
and from where.

Nothing here touches a Transaction. Queueing a command for a Client requires
the admin password or that one capability - never nothing - so a bogus entry
can still only ever collect commands an Admin, or a delegate the Admin handed
that password to, deliberately sent to it.

## What "the source address it saw" means behind a proxy

Added by #187. The server adds the address it saw, and on the one deployment
that is supported it was not seeing the Client at all: under IIS,
HttpPlatformHandler owns the port, starts this process on
`%HTTP_PLATFORM_PORT%` and proxies each request to it over loopback
(ADR-0001), so the peer of the connection this process reads is `127.0.0.1`
for every Client there has ever been. Machines reach this server over a VPN,
so that is a diagnostic thrown away rather than a cosmetic one - the column
whose whole job is to say where something came from said nothing, and
`system_log.address` beside it said the same.

`_client_addr()` in `server.py` answers it now: the peer, unless the peer is
loopback, in which case the leftmost entry of `X-Forwarded-For`. The condition
is the whole security of it rather than a tidiness about proxies. This endpoint
is unauthenticated by design, which is the subject of this ADR, so a header
believed from an arbitrary peer would let anybody on the network write any
address they liked into this column - worse than the honest `127.0.0.1` it
replaces, because a wrong address is read as a fact where a loopback one is
visibly one hop's worth of nothing. A peer that is not loopback is talking to
this process directly, so its own address is the answer and no header can
displace it.

Nothing in IIS sets that header on its own: HttpPlatformHandler's configuration
reference documents exactly one header it adds to the proxied request,
`X-IIS-WindowsAuthToken` under `forwardWindowsAuthToken`, which this deployment
has off. So `tools/install-iis.ps1` sets it, out of IIS's own `REMOTE_ADDR`,
through the URL Rewrite module - and because that module is a separate download,
the rule is written through IIS's configuration API and only where it is
present, a `<rewrite>` section in a `web.config` on a machine without it being
a 500.19 and a site that does not start. Where the rule is not there no header
arrives, the peer is recorded, and the behaviour is exactly what it was.

## Why the Client's own identifier is the key

Neither the hostname nor the address can be. Both move — a machine is renamed,
a DHCP lease changes — and either as a key would fill the table with duplicates
of one installation while the Admin is trying to work out how many there are.
So both are recorded as facts *about* the installation, and neither is its
identity: the hostname is the label a human recognises, and the address is what
the Admin needs when they have to go and find the machine.

The identifier is generated by the Client and kept in its configuration, which
means a reinstall that clears the configuration appears as a new installation.
That is correct — it is one. The cost is a stale row for the previous install
of the same machine, which ages out visibly as a Client nobody has heard from,
and which the Admin can read for what it is.

## Why a state rather than a live connection

Nothing here reports that a Client *is* connected. The list says when each was
last heard from, and the Server GUI colours that: heard from in the last
quarter of an hour, in the last day, or longer than that. A Notifier that has
not checked in for a week is the case the list exists to make visible — the
store keeps working while the verification step quietly stops, because nobody
is being asked to confirm anything.

## When to revisit

- If the registry is ever used to *decide* something rather than to inform an
  Admin — refusing a submission from an unknown Client, say. Then a row an
  outsider can write becomes a control they can defeat, and the identifier
  needs to be something they cannot guess or claim.
- If Clients ever run outside the internal network, per ADR-0002's own trigger.
- If a second credential is ever given `GET /clients`, or if it stops being a
  credentialled read. The property above is the whole of what makes an
  unauthenticated check-in safe to keep: the map goes out behind a password
  and comes in behind none.
- If the number of installations grows past what one window can list, at which
  point the unbounded write becomes worth limiting rather than just recording.
