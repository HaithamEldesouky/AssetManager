---
status: accepted
---

# A certificate rotates in two phases

Every client pins `ssl_cert.pem` and fails closed against anything else (rule
1). `_SelfSignedAdapter` in `common.py` loads that one file as the whole of its
trust store, so a request to a server presenting anything else raises rather
than connecting. That is the property the whole design rests on: one certificate
is enough to impersonate this server to every laptop in the department, and
nothing in the system store can vouch for a self-signed one, so there is no safe
automatic fallback to have.

What it costs is that **replacing the certificate strands the fleet**. The
moment a new certificate is bound, every client holding the old one stops being
able to reach the server - and the hourly `GET /cert` refresh, which is the
mechanism that would have handed them the new file, cannot get through either,
because it runs over the connection the old certificate verified. There is no
channel left. Each machine then has to be visited: `ssl_cert.pem` deleted so the
ADR-0010 first-contact prompt fires, and somebody standing there to read the new
fingerprint and accept it.

Before this, the console offered exactly one way to change the certificate:
Install Certificate, which writes both files and restarts. That is the binding
step with nothing in front of it. An Admin doing routine maintenance - a
certificate a year from expiry, a machine that has been renamed, a SAN that was
missing an address - had no way to do it that did not begin with an outage of
the whole fleet.

## The decision

**A rotation is two phases, and the first one changes nothing.**

Phase one generates a new key and a new self-signed certificate and writes them
beside the server as `ssl_cert_next.pem` and `ssl_key_next.pem`. Nothing is
bound, nothing is served and no client is affected: the listener stays on
`ssl_cert.pem`, `GET /cert` goes on serving `ssl_cert.pem`, and the staged pair
is two files nothing in the request path resolves. The Server Settings window
shows the live fingerprint and the staged one together and says on its face that
no client can reach the new one yet.

Phase two is the cutover, and it is the phase that has to be earned: the staged
certificate is pushed to the clients **while the old one is still being
served** (C3), so each installation holds the next certificate before anything
moves, and only then is the binding changed (C4) - by which time the fleet is
already carrying what it will be asked to verify. The Connected Clients window's
`Certificate` column (C2) is what says whether that is true yet, which is why
that ticket came first: it is the one place the question "who would break if I
cut over today" is answered.

## Why staged files rather than a certificate store

`New-SelfSignedCertificate` puts a certificate in `Cert:\LocalMachine\My`, which
is where `install-iis.ps1 -SelfSigned` leaves the one it binds. That is the
right home for a certificate IIS is going to bind and the wrong home for one
that is deliberately bound to nothing: a certificate in the store is a thing
somebody can bind by accident from the IIS console, and the file the clients
actually pin is a PEM regardless, so a rotation that lived in the store would
have to be exported into these same two files before it could be pushed
anywhere. Two files beside the server, with names that read as what they are,
are the honest shape.

## Why the server generates it, and not a script

`tools/` cannot answer this. `install-iis.ps1 -SelfSigned` generates and binds
in one run, which is precisely the thing being taken apart, and a second script
that generated without binding would be a tool an Admin has to be at a
PowerShell prompt on the server to run - while the window that shows the live
fingerprint, the window that lists which clients hold it, and the window that
will push the new one are all in the Server GUI. It also puts `cryptography` in
`requirements-server.txt` for the first time, guarded at the call site like
`pillow`: an install whose vendored `lib\` predates this refuses that one button
naming `install-iis.ps1 -SelfSigned` instead, rather than failing to start.

The certificate carries `CA:TRUE` and an **IPAddress** SAN as well as the DNS
ones, for `install-iis.ps1`'s reason: each client loads the file as its own
trust anchor, urllib3 asserts the SAN regardless of `check_hostname`, and
OpenSSL 3 refuses a non-CA certificate as an anchor. Each of those fails
silently if omitted. The names default to **this machine's own identity** -
computer name, FQDN where there is one, `localhost`, and the IPv4 on the
interface carrying the default route - never to one deployment's literals, which
is the bug that minted certificates for `asset-server` on every other machine.

## Why the push is a signal and not a payload

Phase two pushes by queueing a Client command, `trust_cert`, that carries **no
certificate at all**. `client_commands` has no payload column, and a command is
handed over **exactly once** - collected in the same transaction as the check-in
that took it, so that a laptop which crashed mid-logoff is not logged off for
ever. A payload inherits that: a hand-over lost between the server committing
the collection and the client writing the file would strand that machine
permanently, with the server holding a `collected` row saying it had been told
and the duplicate guard refusing to reissue. A **signal** is re-issuable, and
re-issuing it costs nothing because the append is idempotent - a client that
already holds the staged certificate writes nothing and says nothing.

The fetch is then the client's own, `GET /cert/next` through the pinned session
like every other request. Nothing here is the ADR-0010 bootstrap and nothing
here runs over an unverified connection: this client is asking a server it
already verifies for a second certificate to accept later, which is a smaller
thing than the first-contact prompt and needs no person at the machine.

## Why the client ends up with a bundle

`load_verify_locations` reads a file holding several certificates as a set of
anchors, so appending rather than replacing leaves the client verifying against
**either** the served certificate or the staged one. That is the whole
mechanism: the window in which a machine can be cut over safely is the window in
which it holds both, and appending opens that window without closing the one it
is already in. Replacing would be the cutover itself, done client by client, in
the wrong order and with no way back for a machine that was switched off.

Every other answer leaves `ssl_cert.pem` byte for byte as it was, and the write
goes to a temporary file and is moved over the real one. That file is the
installation's only trust anchor, and a client with a damaged one cannot reach
the server to be told anything ever again - so a 404, an unreadable body, base64
that will not decode and a pinned file that is not a certificate bundle are all
the same answer, which is to do nothing.

## What the console can and cannot see

The `Certificate` column (C2) reports what each Client says it holds, and a
Client reports the fingerprint of the **first** certificate in its file. After
an append the served certificate is still first - deliberately, it being the one
still in use - so the column does not move and **cannot** be the measure of who
has trusted the staged one. The push therefore queues for every Client rather
than for a count of who is behind, and what answers "who has not done it yet" is
the command queue itself: a row is `queued` until that machine checks in and
`collected` afterwards, which is a fact the server observed rather than one a
client asserted. A number derived from the column instead would have read as a
fleet status and been the opposite of one, which is the failure ADR-0005 already
records about believing a client's own claims.

## Where the Admin is standing when they push (#174)

Phase two is reachable from the Notifier's Remote Admin window as well as from
the console, behind the **Server Settings** capability password over HTTPS or
the admin password (ADR-0015): `POST /clients/push_cert`, forwarding to the
same `_push_next_cert` the Connected Clients window calls. Nothing above
changes - it is still a signal and not a payload, still queued through
`_queue_command` per Client so the duplicate guard holds, still one
`cert.pushed` naming the fingerprint, and still refused outright where nothing
is staged.

What is deliberately **not** reachable is phase one and phase three. Generate
writes `ssl_key_next.pem` and Cut over replaces `ssl_key.pem`, and the SSL
Certificate capability is not in `CAPABILITY_REMOTE` precisely because a key is
the one file that must never travel (rule 1). So the half of this rotation that
touches no key is delegable and the halves that do are not, which is the same
line drawn in the same place rather than a new one - and what a delegate can do
with the push alone is make the fleet accept a certificate nothing is bound to,
which is what the append being idempotent and carrying no payload already makes
safe to re-issue.

## What does not change

The live pair is never written by the generator, and that is asserted rather
than assumed: `ssl_cert_next.pem` and `ssl_cert.pem` are a few characters apart
and one of them strands the fleet. `ssl_key_next.pem` never leaves the machine,
exactly as `ssl_key.pem` does not - not packaged, not exported, and named in a
backup's manifest as something deliberately left behind (ADR-0019). Generating
twice replaces the staged pair and says which fingerprint is staged afterwards;
a staged certificate nobody can name is one nobody can compare a client's report
against.

And **ADR-0010 is still the floor**. A cutover done wrong, or a client that was
switched off for the whole of phase two, still ends with an installation holding
a certificate the server no longer presents. That client fails closed, its
`ssl_cert.pem` is deleted by whoever is at the machine, and the first-contact
prompt asks a person to confirm the fingerprint against what the console shows.
This ADR is about making that the exception rather than the procedure.

A daily background check (#273) reads the live certificate's own expiry and
writes a System Log `warn`, then an `error`, as it approaches - it only warns;
staging and cutting over stay something an Admin still does on purpose.

## What the cutover itself does, and what it deliberately leaves

Phase three replaces two files and nothing else. The live pair is copied
into `cert_rollback\` first, the directory being emptied on the way so exactly
one generation is kept: what is in there is a **private key**, and a keep-
everything shape like `restore_aside\`'s would be another copy of the one file
that must never travel (rule 1) for every rotation this server has ever had.
The generation that is kept is the pair that was live a moment ago, which is
the only one anything could be rolled back to.

The certificate is replaced **before** the key, and the order is not arbitrary:
for the instant between the two writes the pair on disk disagrees, and a
certificate without its matching key fails to bind on the next start, loudly,
where a key without its certificate binds the **old** certificate under the new
key's name and fails quietly - a server that starts, reports healthy and
presents something no client agreed to. The System Log entry is written before
either write rather than after, because what follows a cutover is a restart,
and an entry written after one is an entry that goes missing.

**The binding is not this server's to move.** Under IIS this process is the app
pool identity and is not an administrator, so the console spawns `tools\bind-cert.ps1`
elevated and says plainly that the files are in place and the binding has not
moved yet. A refused elevation is an ordinary answer rather than a failure - by
then the files really are swapped - so what is owed is the exact command, and it
is the one the spawn would have run rather than a second spelling of it. Where
nothing binds here at all, this is also where `ssl_enabled` in
`server_config.json` is turned on (#266): a standalone server or the Windows
Service reads that flag itself rather than terminating TLS at a site, so a
server still on plain HTTP when it staged and cut over would otherwise go on
serving HTTP afterwards, files swapped and nothing offering them. The console
restarts it the same way Install Certificate does, rather than only saying
to.

**Install Certificate is this same act with C1-C3 left out**, and since 070 it
takes the same elevated half. It replaces the same two files; what it does not
have is a fleet that was pushed the new certificate first, which is the whole of
what makes a rotation safe and is why it is still the blunt way to do this. It
used to restart instead, and under IIS the restart it reached was `os.execv` of
the GUI process - the service being disabled there (ADR-0001) - so the site went
on presenting the certificate it was bound to while the popup named the new one.
**Remove Certificate is refused under IIS outright**, before the confirmation
and before either file is deleted. Deleting them turns https off nowhere: the
site terminates TLS and goes on doing it, `GET /cert` starts answering 404, and
every pinned client is stranded with no channel left to hand it anything - this
ADR's own opening failure, reached through the one control that sounds like a
way back from it. What the site serves is changed by `install-iis.ps1` and by
nothing in the console.

## What was rejected

**Serving both certificates at once.** A listener can only present one
certificate per connection without SNI trickery, and the clients do not send a
distinguishing name; a second listener on a second port would mean every client
learning about a port it has no way to be told about, over a connection it
cannot make.

**Shipping the new certificate in a client update.** The update path is a zip of
`.py` files fetched through the pinned session (rule 12, rule 1), and
`client_update.py` deliberately never touches `ssl_cert.pem` - it is not in any
manifest. Folding a trust anchor into a software update would mean a client
adopting a new anchor because a zip said so, with no person confirming anything,
which is the thing ADR-0010 exists to refuse.

**Making it one button that generates and binds.** That is what exists already.
The whole content of this ADR is that the two halves are separated by however
long it takes the fleet to pick the new certificate up, and that the console can
say when that has happened.
