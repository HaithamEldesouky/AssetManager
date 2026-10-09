# 030 - The Asset Server can send mail

**Type:** feature · **Depends on:** 023 · **Needs an ADR**

## What changes

An SMTP client in `server.py`, configured from the Server GUI, and one function -
`_send_mail(to, subject, body)` - that everything else calls.

Configuration is a card reached from the Server GUI (beside Display Settings' neighbours,
not on the action row, which is measured at six full labels using 846px of 964px): host,
port, from-address, STARTTLS on/off, username, password, and a **Send test mail** button
that reports the server's own error text rather than "failed". Stored in
`server_config.json` except the password. Every change takes the **admin password** -
whoever can point this at a mail server can mail the department as the Asset Server.

## The password is a new kind of secret, and that is the whole risk

Everything stored today is a one-way salted hash (ADR-0008): nothing on this machine can
recover a password, which is why a stolen `admin_config.json` is not a stolen password. An
SMTP password has to be **replayed** at every send, so it has to be recoverable, and it is
the first such secret this system holds.

It is stored with **Windows DPAPI at machine scope** (`win32crypt.CryptProtectData`,
pywin32, already a server dependency and already guarded behind `HAS_WIN32SVC`'s idiom for
an import that may not be there). Encrypted at rest, decryptable only on that machine by
that account, no key file to manage and none to leak. It lives in a file of its own,
`smtp_secret.dat`, **not** in `server_config.json` - that file is read-modify-written by
`install-iis.ps1`, by `installer.py` and by `dev-run.ps1`, none of which should ever be
holding a ciphertext they might rewrite.

Where DPAPI is unavailable (a source install without pywin32), the password field is
**refused with a message naming why**, rather than falling back to plaintext. An
unauthenticated internal relay still works there, which is the better deployment anyway.

An **ADR** records this: what ADR-0008 does not cover, why DPAPI rather than a key file,
and why the failure mode is a refusal rather than a fallback.

## `_send_mail` never breaks a request

The same contract `_log_event` has, for the same reason and stated in the same place:
**it never raises and never waits long**. A connection timeout is short and bounded, a send
happens on a worker rather than inside the request that triggered it, and a mail server
that is down or full can never turn a recorded Transaction into a refused one. A failed
send is a System Log entry at `warn` - which is the only place anybody will look.

## Verification

`tools/server-checks.py`: `_send_mail` against a stub SMTP that raises, times out and
succeeds, asserting no exception escapes and a Transaction still records; that the password
never reaches `server_config.json`, never reaches a `_log_event` call, and never appears in
the test-mail message; and that the config round-trips without the secret.

## Not in this ticket

Which events are mailed and to whom - 031. This ticket gives the system a way to send and
sends nothing on its own but the test mail.

## As built

Done as filed. Two things the ticket left to the implementation are decided
here, and one sentence in it turned out to be wrong about its own choice.

- **The card is the fourth footer button in Change Admin Password**, beside
  Capability Passwords, Engineer Passwords and Manage Users. The ticket says
  "beside Display Settings' neighbours, not on the action row", and the
  neighbours it means are the three doors that already hang off that dialog.
  The adjacency argument is the one that window already makes: who holds which
  password is its subject, and this is the only password on this machine that
  something can read back. A Mail chip in the status card was the alternative
  and was rejected - that row measured 811px of 956px before the Database chip
  widens with a moved database, and mail is not a fact about this server the
  way its host and its port are.
- **The ticket's own DPAPI sentence says "on that machine by that account", and
  the scope it names is machine scope, which is not that.** Machine scope is
  what is built and ADR-0013 says why: one install is opened by three different
  accounts - the interactive Admin at the console, LocalSystem under the
  Windows Service, and the app pool identity under IIS - so user scope is a
  secret that works while somebody is logged in and stops silently when they
  are not, with the GUI's own test mail passing throughout. That was already
  the decision taken when this chain was planned; the ticket's gloss on it was
  the part that was wrong.
- **Two functions rather than one with a flag.** `_smtp_send_now` does the send
  and answers with the mail server's own words or `""`; `_send_mail` starts a
  worker on it and answers whether one was started. The test mail is the only
  caller that waits, because an Admin is standing at the console and the answer
  is the whole point of the button. A `wait=` flag would have put "may this
  block?" at every call site, which is the decision that must not be gettable
  wrong.
- **Send test mail saves first.** A test that passes against what is in the
  form and then fails against what is in the file is worse than no test, and
  the fields the two would differ on - the relay, the sender, the password -
  are exactly the ones a test exists to check.
- **`_send_mail` answers False for an unconfigured server and starts nothing**,
  so 031 can call it for every event without first asking whether mail is set
  up. A server with no relay configured sends no mail and that is not an error
  anywhere.

## Verified

- `tools/server-checks.py` (127 groups), `tools/cascade-audit.py` (no drift)
  and `tools/client-checks.py` (12 groups) all exit 0.
- The two new server-check groups drive a stub SMTP that refuses the
  connection, times out and refuses the login: each comes back as that server's
  own sentence with nothing raised, and beside each one a Transaction is
  recorded, Confirmed and Rejected. The failed send lands as exactly one
  `mail.send_failed` at `warn` naming the recipient, the subject and the error,
  and never the body.
- The password: stored through DPAPI and read back, the ciphertext on disk not
  containing it, `server_config.json` not containing it in any form and holding
  no key that names it, no System Log row anywhere containing it, and the test
  mail not carrying it - while it is replayed to the mail server and nowhere
  else. Clearing it removes the file.
- The real window opened and driven: a wrong admin password changes nothing, a
  right one saves and the change is on disk at once, the test mail is sent and
  reported as accepted, and a refused login is reported in the mail server's
  words. Measured 560x834, which holds its children's 558x834.

## Not done here

Which events are mailed and to whom stays 031, as filed. Nothing in this ticket
sends anything on its own but the test mail.
