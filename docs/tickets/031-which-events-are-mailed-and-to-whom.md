# 031 - Which events are mailed, and to whom

**Type:** feature · **Depends on:** 030

## What changes

011 gave every component one writer, `_log_event`, and a stable short event name -
`transaction.created`, `auth.refused`, `lookup.saved`. This ticket lets an Admin say which
of those names reach a mailbox.

A **Notification Rules** window beside the SMTP card: one row per subscribed event -
the event name, the recipients, and the minimum level. The rules are stored in
`server_config.json` (no secret in them) and are **read from disk on each send**, not from
the import-time snapshot - the same rule `storekeeper_can_cancel` follows, and for the same
reason: an Admin who has to restart the server to stop a flood will not reach for the switch
in the situation that made them want it.

The hook is **one call inside `_log_event`**, after the row is written, and nowhere else.
Not a second call site per interesting event: a rule pointed at an event nobody emits mails
nothing, which is visible and harmless, whereas an event somebody forgot to wire mails
nothing and looks configured. `_log_event`'s own promise stands - it still never raises and
never waits long - so the send is handed off, never awaited.

**Two bounds, for the reason retention has two.** `POST /clients/log` is unauthenticated
(ADR-0002, ADR-0005), so anybody on the network can write log entries as fast as they like,
and a rule on a client-shipped event is a mail amplifier pointed at the department. A
per-event rate limit and a per-hour ceiling across all rules, both stated in the window, and
a suppressed burst reported as one summary mail rather than silently dropped.

A rule may be set on any event name, including one that does not exist yet, and the window
offers the names actually seen in the log as its list - it is not a second copy of an event
catalogue (rule 10 would be the next complaint).

## Verification

`tools/server-checks.py`: an event with a rule sends and one without does not; a send that
raises does not break `_log_event`'s contract or the Transaction behind it; the rate limit
and the ceiling hold under a burst and the summary names the count; a rule is re-read from
disk after the file changes without a restart.

## Not in this ticket

Mailing a Storekeeper's proposal (028) or a sync result (032) - both emit System Log events
already, so both are covered by a rule rather than by code here.

## As built

Done as filed. Everything the ticket names is there and in the shape it named;
what follows is the three places it left a choice open.

- **A window of its own, opened from Mail Settings' footer**, rather than a
  second half of that card. The relay and the credential change for entirely
  different reasons than the subscription list does, and one window would ask
  for the admin password once for two decisions an Admin makes months apart.
  That is the adjacency Capability Passwords has to Change Admin Password.
- **The two bounds are counters in this process, not rows.** A bound that reset
  on every log write would not be a bound, and a bound in the database would be
  a write on the path of a function whose whole promise is that it never waits
  long for one. The cost is that a restart forgives whatever was being held -
  which is the right way round: a restart is not a flood.
- **What was held rides the next mail that event does send**, rather than a
  timer of its own. A burst is by definition still firing, and a scheduled
  summary would be a second thing that can go wrong between the bound and the
  reader. An event that fires once more and then never again leaves its count
  unreported, and the window says the System Log has all of it either way.
- **`mail.*` is excluded here rather than left to whoever writes the rule.**
  `_send_mail`'s worker logs its own failure, so a rule on `mail.send_failed`
  would mail about the mail that could not be sent, fail again, and log again.
  One name, one line, no loop.
- **The hook is handed the row's own values**, not the arguments behind them:
  what a rule matches on and what a reader is mailed has to be what was stored,
  capped and defaulted exactly as the table holds it. And it sits in a `try` of
  its own rather than the write's, which is the load-bearing part - inside the
  outer one, a broken mail layer would make `_log_event` answer False about a
  row it really wrote, and `POST /clients/log` reads that answer.

## Verified

- `tools/server-checks.py` (130 groups), `tools/cascade-audit.py` (no drift)
  and `tools/client-checks.py` (12 groups) all exit 0.
- Three new gate groups: that a rule mails its event and the absence of one
  mails nothing, that an unreadable hand-edited rule is ignored rather than
  raised on, that the level floor holds, that a `mail.*` rule is never acted
  on, and that a rule written to the file takes effect with no restart; that
  six entries are one mail and the count it held rides the next one, and that a
  hundred *different* events stop at the ceiling, which is the half the
  per-event limit cannot do alone; and that a `_send_mail` which raises leaves
  the row written, the writer still answering True, and a Transaction still
  recorded, Confirmed and Rejected.
- The real window opened and driven against a stub SMTP: a rule typed in and
  saved with the admin password lands in `server_config.json` and is read back
  by `_notify_rules`, a wrong password changes nothing, and the event dropdown
  offers the names the log has actually seen. Measured 680x457, which holds its
  children's 643x457.

## Not done here

Mailing a Storekeeper's proposal (028) or a sync result (032) - both emit
System Log events already, so both are a rule rather than code, exactly as
filed.
