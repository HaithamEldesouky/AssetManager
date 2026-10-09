---
status: accepted
---

# A client pins the certificate on first use, and a person confirms it

A client with no `ssl_cert.pem` beside it used to raise on every `https://`
request and tell whoever was there to re-run the installer. That is correct and
it is a dead end: the installer is not always to hand, the file it bundles is
the certificate that existed on the build machine at build time, and an
engineer whose copy went missing has no way back except somebody carrying a
file to their desk.

A client with no certificate now fetches `GET /cert` once, over a connection
that verifies nothing, shows the SHA-256 fingerprint of what came back, and
writes the file **only if a person accepts it**. That is trust on first use,
and the first use is answered by a human reading the fingerprint off the Server
GUI's SSL Certificate dialog on the server itself (#33 put it there).
Afterwards nothing is different: the file is pinned, every request goes through
`load_verify_locations` against it, and the hourly refresh runs over a
connection that pin has already verified.

## What trust on first use actually costs

For the length of one GET, the client will talk to whatever answers for
`asset-server` on that port, and it will not know it has been answered by the
wrong thing. On an internal domain network that window needs somebody already
on the wire and already able to be that name — ARP or DNS poisoning, or the
machine itself. It is a smaller window than it looks (one GET of a public file,
no credential, no check-in, no transaction crosses it) and a bigger consequence
than it looks: what gets pinned is pinned permanently, so an attacker who wins
the window owns every later connection from that client, including the one that
carries the admin password into Settings.

That consequence is the whole reason the fingerprint is shown rather than
assumed. The unverified fetch is not the trust decision — the person is. The
network answers *what* the certificate is; the human answers *whether it is the
right one*, out of band, off a screen on the server.

## Why the confirmation is not skippable and has no default-yes

An OK/Cancel with Cancel as the default keyboard action, `icon="warning"`, and
no "remember this" and no "always trust": the failure mode of a fingerprint
prompt is not that people cannot read it, it is that they are trained to
dismiss it. So a refusal is not re-asked, which matters more than it sounds:
the clients tick every fifteen seconds, and a refusal that could be re-asked
would be a dialog every fifteen seconds until it was accepted. That is a
machine for teaching somebody to click OK without reading. Restarting the app
asks again — a person who wants to answer differently can, deliberately.

That bound is one prompt per **process** for anything that ticks, and one per
**deliberate attempt** for anything that does not. The installer is the second
kind and was held to the first, which cost it the whole of what this section is
protecting rather than buying any of it: there is no loop behind a click on
Install, so a refusal there could not train anybody to dismiss anything, while
the refusal that did happen — Cancel being the default button, one stray
keypress away — left every later click in that process failing closed with
no file on disk and reported as a server that could not be reached, with the
one sentence offering a way out naming an offer that could no longer come. So
`common.reset_cert_prompt()` re-arms the question and `installer.py`'s
`_install` is its one caller: the rule stays written down in the module that
owns the decision, rather than in a latch another module reaches into. It
re-arms the question and never the trust — a certificate already on disk is
still not re-offered, that being a different condition and one nobody should be
asked to re-accept.

An app that registers no callback, or has a Tk root that cannot be reached
because there is no main loop yet, or a person who never answers, all end the
same way: nothing is written and the request fails closed exactly as it did
before this existed. Nobody watching means nothing pinned.

## Why only `GET /cert` crosses the unverified connection

The unverified path is a bare `http.client.HTTPSConnection` with its own
context inside one function, not `verify=False` and not a relaxed adapter on
the shared session. Two reasons, and the second is the real one:

- `verify=False` is banned outright (rule 1), and it is banned because it is a
  flag anybody can add to any call. A separate connection cannot be reached by
  the rest of the file at all.
- The shared session's adapter is the *pinned* one. Every other request in
  `common.py` goes through it and still refuses with no file on disk — the
  check-in, the password verification, the transaction flush. Relaxing that
  adapter for the bootstrap would put an unverified path within reach of all of
  them, which is the failure this design exists to avoid rather than a detail
  of how it is written.

The body is capped at 64 KB, is refused unless it holds a `BEGIN CERTIFICATE`
block, and is refused outright if it holds a `PRIVATE KEY`: a server serving
its own key is either a misconfiguration nobody should paper over or something
pretending to be the server. `package.ps1` and `bundle-client.ps1` refuse the
same thing for the same reason.

## Why the prompt lives in the app and the logic in `common.py`

`common.py` computes the fingerprint, writes the text, decides whether to ask
and what to do with the answer; the app supplies a callback through
`set_cert_confirm` and owns the window. The transport layer opening a Tk dialog
would be the same mistake as it deciding what a queued `logoff` means: the
Notifier's tray thread, the Storekeeper's window and the installer's modal are
three different acts. Rule 10 keeps the logic in one place; the window stays
app-local.

Marshalling is `confirm_on_tk_thread`, because both clients call `api()` from
worker threads and a Tk call from one raises. It hands the question to the Tk
thread with `after(0, ...)` and waits; if `after` raises — no main loop yet,
which is the `fc39de7` class of bug — or nothing answers within five minutes,
the answer is no.

## What was rejected

- **Silent trust on first use** — fetch, pin, say nothing. It is what every
  "just make it work" version of this looks like, and it hands the whole
  consequence above to whoever happens to answer during a window the user never
  knew opened. The pin is permanent and the next Settings unlock carries the
  admin password. The prompt is not friction to be optimised away; it is the
  entire security property.
- **Keeping installer-only.** Correct, and the status quo, and it fails the
  case that prompted this: a client that cannot reach the server also cannot be
  told anything, and the remedy involves a person and a USB stick. It is kept
  as the *quiet* path — an install given a certificate never prompts.
- **Pinning what the TLS handshake presented** instead of `GET /cert`. It is
  strictly less that crosses the wire, and for a self-signed server the two are
  the same bytes. But `/cert` is the file the Server GUI shows the fingerprint
  of, and the fingerprint a human compares must be of the thing being pinned,
  not of something that ought to equal it.
- **Pinning the fingerprint the user types in** rather than showing one to
  accept. Thirty-two pairs of hex read aloud over a desk phone is a worse
  reading task than comparing two, and a mistyped fingerprint fails in a way
  nobody can diagnose.
- **A "trust this network permanently" setting**, which is the same as silent
  TOFU with a switch to blame afterwards.

## Consequences

- The certificate stops being required at install time. `bundle-client.ps1`
  still warns when it has none to ship and `package.ps1` still refuses to build
  a package that cannot supply one — a supplied certificate is still the better
  outcome, because nobody has to read anything.
- A client can now be stood up against a server whose certificate has been
  replaced, without a reinstall — the old pin fails, the file is deleted by
  hand, and the next start offers the new fingerprint.
- One unverified connection now exists in client code where none did. It is one
  function, it is reachable from one caller, and `tools/client-checks.py`'s
  source group is where a check belongs if a second one is ever attempted.

- It is also the floor under a certificate **rotation** (ADR-0020). A
  cutover done wrong, or a client that was switched off for the whole of
  it, still ends with an installation holding a certificate the server no
  longer presents - and this is what it falls back to: the old pin fails,
  the file is deleted by hand, and a person confirms the new fingerprint.
  ADR-0020 is about making that the exception rather than the procedure.

## When to revisit

- If the server ever gets a certificate from an internal CA. Then the CA is the
  trust anchor, the clients verify a chain, and this whole mechanism is
  unnecessary rather than merely reduced.
- If a client is ever run somewhere nobody is sitting — a service, a scheduled
  task. It fails closed there today, which is right, but the answer would be a
  provisioned certificate, not a relaxed prompt.
