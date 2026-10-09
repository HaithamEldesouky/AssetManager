"""
Asset Manager - mail, and which events are mailed.

What this server can send (`_smtp_cfg`, `_smtp_secret_set`,
`_smtp_secret_get`, `_smtp_secret_stored`, `_save_mail_settings`,
`_send_test_mail`, `_smtp_send_now`, `_send_mail_worker`, `_send_mail`) and
the rules that decide which System Log entry reaches a mailbox
(`_notify_rules`, `_save_notify_rules`, `_notify_gate`, `_notify_of`).

Lifted out of `server.py` by #224 unchanged - the first of the six clusters
046 (#220) named and left in it. Two banners rather than one because they are
one concern read twice: a rule is what says an event is worth mailing, and
`_send_mail` is the only thing that can send it. Neither half is the routes'
and neither is the console's - `POST /admin/mail`, `/admin/mail/test` and
`/admin/notify_rules` stay in `server.py`, `server_gui.py`'s Mail Settings and
Notification Rules windows reach these as `S.<name>`, and
`tools/server-checks.py` drives most of them directly rather than over HTTP.

**Two names under the Mail banner did not come with it.** `_secret_set` and
`_secret_get` are the generic stored-secret pair: the mail relay's password
(ADR-0013) is one caller and the external asset system's credential
(ADR-0014) is the other, and that second one is in the cluster 051 moves.
They sit under that banner because mail needed them first, not because they
are mail's, so they stayed in `server.py` and come back through `bind()`.
`_DPAPI_LOCAL_MACHINE` stayed with them, being the scope those two encrypt at
and read nowhere else.

**`_notify_of` is called from `server.py`, once, inside `_log_event`** - after
the row is written and nowhere else, which is what makes a rule the only thing
that decides what is mailed. That call is the seam with 053: when the System
Log becomes a module of its own it will reach this one the same way round.

Headless-safe: nothing here draws, so `server.py` imports it at module level.

**It opens no file and reads no config of its own.** `_load_server_cfg`,
`_save_server_cfg`, `_validate_port`, `_log_event`, `_secret_set`,
`_secret_get`, `SMTP_SECRET_PATH` and `LOG_LEVELS` are all `server.py`'s and
come over through `bind()`, handed rather than imported back for the reason
`server_cert.py`'s docstring gives - `server.py` runs as `__main__` under
`applaunch`'s `runpy.run_path`, so `from server import _log_event` would
execute the whole server a second time rather than reach the one running.

`_KEEP` is the one name imported rather than bound, and it comes from
`register_engineers` rather than from `server.py`. `_save_mail_settings`'s
signature *defaults* to it, and a default is evaluated at import: a sentinel
assigned by `bind()` afterwards would leave that default holding the `None`
this module loaded with while its two callers compared against the bound
object, and every form that left the password alone would read as clearing
it. So it is imported from the module that defines it - a peer, the way
`register_transactions` imports `register_assets`, never `server`.
"""

import os
import smtplib
import socket
import threading
import time
from email.message import EmailMessage

# The sentinel `_save_mail_settings` defaults to, from the module that defines
# it beside the `_save_member` signature that does the same. Imported rather
# than bound because a default argument is evaluated at import; see the
# docstring above.
from register_engineers import _KEEP

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
LOG_LEVELS = None
SMTP_SECRET_PATH = None
_load_server_cfg = None
_log_event = None
_save_server_cfg = None
_secret_get = None
_secret_set = None
_validate_port = None
event_sentence = None


def bind(*, log_levels, smtp_secret_path, load_server_cfg, log_event,
         save_server_cfg, secret_get, secret_set, validate_port,
         event_sentence):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `server_cert.bind()` and
    the three registers' carry: every name the moved code reads out of
    `server.py` is on this list, built with a `symtable` sweep over the moved
    block rather than by hand, because 036's own note found fourteen names a
    hand-written list had missed. `event_sentence` is the ninth, added by
    #071 so `_notify_of` renders through the one sentence the window and the
    export already do rather than composing its own line.

    Two of the eight names that block above `event_sentence` are `_secret_set`
    and `_secret_get`, which stayed behind rather than answering only to mail -
    the external asset system's credential is the other caller of the pair,
    and 051 is the ticket that moves that one.

    Called from `server.py` beside `_secret_get` rather than in the block that
    binds the registers, because those two are defined below that block and
    a name handed over before it exists is the one real failure mode of this
    pattern.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports a
    second, and it gives each staged copy a `server_mail` of its own.
    """
    global LOG_LEVELS, SMTP_SECRET_PATH, _load_server_cfg, _log_event
    global _save_server_cfg, _secret_get, _secret_set, _validate_port
    LOG_LEVELS = log_levels
    SMTP_SECRET_PATH = smtp_secret_path
    _load_server_cfg = load_server_cfg
    _log_event = log_event
    _save_server_cfg = save_server_cfg
    _secret_get = secret_get
    _secret_set = secret_set
    _validate_port = validate_port
    # `global event_sentence` is a syntax error where `event_sentence` is
    # also the parameter, exactly `get_db`'s reason in server_log.py and
    # server_archive.py - so the module global is set the one way left.
    globals()["event_sentence"] = event_sentence


# How long the whole conversation with the mail server may take. Bounded for
# the reason _LOG_DB_TIMEOUT is bounded: whatever triggered the send is in the
# middle of something that matters, and none of them is worth delaying for a
# notification.
_SMTP_TIMEOUT = 10
_SMTP_PORT_DEFAULT = 25


def _smtp_cfg():
    """The mail settings, read from disk on every call.

    Not from the import-time _SERVER_CFG snapshot, for the reason the
    Storekeeper Cancel switch is not read from it: an Admin who has to restart
    the server to point it at a different relay will not reach for the setting
    in the situation that made them want it. The password is not in here
    because it is not in that file at all.
    """
    cfg = _load_server_cfg()
    port, _err = _validate_port(cfg.get("smtp_port", _SMTP_PORT_DEFAULT))
    return {"host":     str(cfg.get("smtp_host", "") or "").strip(),
            "port":     port or _SMTP_PORT_DEFAULT,
            "from":     str(cfg.get("smtp_from", "") or "").strip(),
            "starttls": bool(cfg.get("smtp_starttls", False)),
            "username": str(cfg.get("smtp_username", "") or "").strip()}


_SMTP_NO_DPAPI = ("This machine cannot store a mail password: Windows DPAPI is "
                  "not available here, which needs pywin32. It is never "
                  "written in plaintext instead. Leave the password empty and "
                  "use a relay that does not ask for one.")


def _smtp_secret_set(password):
    """Store the SMTP password, or clear it. Returns "" or a refusal sentence."""
    return _secret_set(SMTP_SECRET_PATH, "Asset Manager SMTP", password,
                       _SMTP_NO_DPAPI)


def _smtp_secret_get():
    """The stored SMTP password, or "". Never raises."""
    return _secret_get(SMTP_SECRET_PATH)


def _smtp_secret_stored():
    """Whether a password is on disk. The only thing about it the GUI is told."""
    return os.path.exists(SMTP_SECRET_PATH)


def _save_mail_settings(host, port, sender, username, starttls,
                        password=_KEEP):
    """The one place the mail settings are written. #172.

    Returns ``(code, message)``, and ``("", "")`` where they were written -
    `_save_asset`'s shape rather than `_delete_member`'s, because both callers
    want the sentence and only one of them wants an HTTP status.

    It exists for the reason `_save_member` exists: the console's Mail Settings
    window and `POST /admin/mail` are two doors onto one decision, and that
    decision is three steps that have to happen in one order - the port is
    validated, the password is written to `smtp_secret.dat` **before** anything
    lands in `server_config.json`, and the settings are read-modify-written
    through `_save_server_cfg`. A second copy at the endpoint would be a second
    place for the DPAPI refusal to be got wrong, which is the one step here
    with no fallback by design (ADR-0013).

    `password` is `_KEEP` where the caller is not touching it, `""` where it is
    being cleared and the password itself where it is being replaced - the
    convention `_save_member` uses, and for its reason: a form that shows no
    password cannot tell "leave it" from "clear it" any other way.

    No System Log entry of its own. `_save_server_cfg` logs the keys that
    change what the server does and these are not among them; what records a
    delegated change is the `remote.action` the door already wrote.
    """
    port, err = _validate_port(port or _SMTP_PORT_DEFAULT)
    if err:
        return "bad_port", err
    if password is not _KEEP:
        err = _smtp_secret_set(password or "")
        if err:
            return "no_secret_store", err
    _save_server_cfg(smtp_host=str(host or "").strip(), smtp_port=port,
                     smtp_from=str(sender or "").strip(),
                     smtp_username=str(username or "").strip(),
                     smtp_starttls=bool(starttls))
    return "", ""


def _send_test_mail(to, actor, address=""):
    """Send the test message and write down which answer came back. #172.

    Waited for, unlike every other send in this file: somebody asked for it and
    the answer is the whole point of the button. One copy of the body and of
    the two entries beside it, because the console and `POST /admin/mail/test`
    are the same act from two places and a test that reads differently
    depending on where it was asked for is a test nobody can compare.
    """
    err = _smtp_send_now(
        to, "Asset Manager test mail",
        "This is a test message from the Asset Server on %s.\n\n"
        "Sent from Mail Settings by %s. Nothing else was changed by sending "
        "it." % (socket.gethostname(), actor))
    if err:
        # The mail server's own words. "Failed" is the one answer nobody
        # can act on.
        _log_event("mail.test_failed", "to %s · %s" % (to, err),
                   actor=actor, level="warn", address=address)
    else:
        _log_event("mail.test_sent", "to %s" % to, actor=actor,
                   address=address)
    return err


def _smtp_send_now(to, subject, body):
    """Send one message and wait for it. Returns "" or the server's own words.

    Never raises: its two callers are a worker nobody is watching and a dialog
    that wants the error text rather than a traceback. What comes back on a
    failure is what the mail server actually said, because "failed" is the one
    answer nobody can act on - a wrong password, a refused sender and a host
    that is not there each need a different thing done about them.
    """
    cfg = _smtp_cfg()
    rcpt = [str(a).strip() for a in
            (to if isinstance(to, (list, tuple))
             else str(to or "").split(",")) if str(a).strip()]
    if not cfg["host"]:
        return "No mail server is configured."
    if not cfg["from"]:
        return "No From address is configured."
    if not rcpt:
        return "No recipient."
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = ", ".join(rcpt)
    msg["Subject"] = subject or "(no subject)"
    msg.set_content(body or "")
    try:
        srv = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=_SMTP_TIMEOUT)
        try:
            if cfg["starttls"]:
                srv.starttls()
                srv.ehlo()
            if cfg["username"]:
                srv.login(cfg["username"], _smtp_secret_get())
            srv.send_message(msg)
        finally:
            try:
                srv.quit()
            except Exception:
                pass
    except socket.gaierror as ex:
        # The commonest failure here, and the one whose own words name nothing
        # at all: "[Errno 11001] getaddrinfo failed" does not say which name
        # was looked up, that a name lookup is what failed, or that the mail
        # conversation never started - so it reads as the relay refusing the
        # mail when the relay was never reached. That is the one answer nobody
        # can act on, which is what this function exists not to give, so what
        # it says is the name it could not resolve: a host pasted in with its
        # port on the end of it, a short name that needs the domain suffix and
        # a plain typo are all read straight off that one line.
        return ('The mail server name "%s" could not be found: %s. Check the '
                'spelling, that this machine can resolve it, and that the '
                'port is in the Port field rather than on the name.'
                % (cfg["host"], str(ex).strip() or ex.__class__.__name__))
    except Exception as ex:
        # Still the mail server's own words, with what they are about in front
        # of them - "timed out" does not say which relay timed out, and this
        # window is where somebody is comparing what they typed against what
        # the relay answered.
        return "%s:%s - %s" % (cfg["host"], cfg["port"],
                               str(ex).strip() or ex.__class__.__name__)
    return ""


def _send_mail_worker(to, subject, body):
    """One send, off the request thread. Its failure is a log line, not a raise."""
    err = _smtp_send_now(to, subject, body)
    if err:
        # Who it was for, what it was about and what the mail server said.
        # Never the body and never the password: this line is read by whoever
        # is working out why a notification did not arrive, and a log is not a
        # copy of the mail.
        who = ", ".join(to) if isinstance(to, (list, tuple)) else str(to or "")
        _log_event("mail.send_failed", "to %s · %s · %s" % (who, subject, err),
                   level="warn")


def _send_mail(to, subject, body):
    """Send one message without waiting for it. The one door everything uses.

    The same contract _log_event has, for the same reason: it never raises and
    it never waits. A mail server that is down, full or simply slow must never
    be able to turn a recorded Transaction into a refused one - that is the
    failure this whole system exists to prevent, and a notification is never
    worth it. So the send happens on a worker rather than inside the request
    that triggered it, and a failure ends as a System Log entry at warn, which
    is the only place anybody will look for it.

    Returns whether a worker was started, which is not whether the mail
    arrived: nothing here waits long enough to know that. A server with no mail
    configured answers False and starts nothing, so 031 may call this for every
    event without first asking whether mail is set up.
    """
    try:
        if not _smtp_cfg()["host"]:
            return False
        threading.Thread(target=_send_mail_worker, args=(to, subject, body),
                         daemon=True).start()
        return True
    except Exception:
        return False



# ─── Which events are mailed, and to whom ─────────────────────────────────────
# A rule is an event name, the mailboxes it goes to and the least level that
# counts. They live in server_config.json because there is no secret in one -
# the password they are read beside is not in that file at all (ADR-0013) - and
# they are read from disk on every entry rather than from the import-time
# snapshot, the same rule storekeeper_can_cancel follows and for the same
# reason: an Admin who has to restart the server to stop a flood will not reach
# for the switch in the situation that made them want it.

# Two bounds, for the reason the System Log's retention has two: POST
# /clients/log is unauthenticated (ADR-0002, ADR-0005), so anybody on the
# internal network can write entries as fast as they like, and a rule on a
# client-shipped event is a mail amplifier pointed at the department. One is
# per event and one is across every rule there is, because either alone can be
# walked around - a hundred events once each defeats the first, and one event a
# hundred times defeats nothing but is what a stuck client actually does.
_NOTIFY_MIN_SECS = 60
_NOTIFY_HOURLY_MAX = 60

# What was suppressed is carried on the next mail that event does send, rather
# than dropped in silence: a reader who is told nothing cannot tell a quiet
# hour from a bound that has been holding all of it back.
_notify_lock = threading.Lock()
_notify_state = {"hour": -1, "sent": 0, "last": {}, "held": {}}


def _notify_rules():
    """The rules, read from disk. Never raises and never returns a bad one.

    Every field is normalised here rather than where it is written, because the
    file can be edited by hand and a rule that cannot be read must be ignored
    rather than break a log write - _log_event's promise is above this one.
    """
    try:
        raw = _load_server_cfg().get("notify_rules", [])
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        event = str(r.get("event", "") or "").strip()
        to = [a.strip() for a in
              str(r.get("to", "") or "").replace(";", ",").split(",")
              if a.strip()]
        level = str(r.get("level", "info") or "info").strip().lower()
        if event and to:
            out.append({"event": event, "to": to,
                        "level": level if level in LOG_LEVELS else "info"})
    return out


def _save_notify_rules(rules, actor, address=""):
    """The one place the notification rules are written. #172.

    Returns ``(code, message, kept)``. `rules` is a list of ``{event, to,
    level}`` as typed; a row with neither an event nor a recipient is the blank
    one every form opens with and is dropped rather than refused, and a row
    with one of the two is refused naming which.

    `_notify_rules` above normalises on the way **out**, because the file can
    be edited by hand and a rule that cannot be read must never break a log
    write. This normalises on the way **in**, which is a different job: what it
    protects is the Admin from writing a rule that will be silently ignored.
    """
    kept = []
    for r in rules or []:
        if not isinstance(r, dict):
            return "bad_rule", "A rule has to be an object.", []
        event = str(r.get("event", "") or "").strip()
        raw_to = r.get("to", "")
        # A list is what `_notify_rules` reads back and so what a caller that
        # fetched the rules before editing them sends; the window one table
        # over holds one Entry per rule and sends the line as typed. Both mean
        # the same rule, so both are taken here rather than at one of the two
        # doors - the other would be the one to get it wrong.
        if isinstance(raw_to, (list, tuple)):
            raw_to = ", ".join(str(a) for a in raw_to)
        to = str(raw_to or "").strip()
        level = str(r.get("level", "info") or "info").strip().lower()
        if not event and not to:
            continue
        if not event or not to:
            return ("bad_rule",
                    "A rule needs both an event name and at least one "
                    "recipient. %s" % (("'%s' has no recipient." % event)
                                       if event else
                                       "One row has recipients and no event."),
                    [])
        if level not in LOG_LEVELS:
            return ("bad_level",
                    "'%s' is not a level. It is one of %s."
                    % (level, ", ".join(LOG_LEVELS)), [])
        kept.append({"event": event, "to": to, "level": level})
    _save_server_cfg(notify_rules=kept)
    _log_event("notify.rules_changed", "%d rule(s)" % len(kept),
               actor=actor, level="warn", address=address)
    return "", "", kept


def _notify_gate(event, now=None):
    """(may this send, how many were held back). The two bounds, applied.

    Held entries ride the next mail that event does send rather than a timer of
    their own: a burst is by definition still firing, and a scheduled summary
    would be a second thing that can go wrong between the bound and the reader.
    """
    with _notify_lock:
        now = time.time() if now is None else now
        hour = int(now // 3600)
        if hour != _notify_state["hour"]:
            _notify_state["hour"], _notify_state["sent"] = hour, 0
        held = _notify_state["held"].get(event, 0)
        if (now - _notify_state["last"].get(event, 0) < _NOTIFY_MIN_SECS
                or _notify_state["sent"] >= _NOTIFY_HOURLY_MAX):
            _notify_state["held"][event] = held + 1
            return False, 0
        _notify_state["last"][event] = now
        _notify_state["sent"] += 1
        _notify_state["held"].pop(event, None)
        return True, held


def _notify_of(event, level, component, actor, detail, ts, data=None):
    """Mail the rules that match one System Log entry. Called from _log_event.

    Never raises - its caller has already written the row and must answer True
    about it - and never waits, because the send goes through _send_mail, which
    hands it to a worker.

    **Nothing named mail.* is ever notified.** A failed send is logged by
    _send_mail's own worker, and a rule on that event would mail about the mail
    that could not be sent, fail again, and log again. One name, excluded here
    rather than left to whoever writes the rule.

    Renders through `event_sentence` since #071 - the window's meaning column
    and the export already do, and a mailed line disagreeing with both of them
    about what a row means would be the one reader with its own opinion.
    `data` is `_log_event`'s own already-capped JSON text (or None), passed
    straight through: what a rule mails is what the row itself holds, not the
    caller's original value where the two differ.
    """
    if str(event or "").startswith("mail."):
        return 0
    rules = [r for r in _notify_rules() if r["event"] == event]
    if not rules:
        return 0
    try:
        want = LOG_LEVELS.index(level if level in LOG_LEVELS else "info")
    except ValueError:
        want = 0
    rules = [r for r in rules if want >= LOG_LEVELS.index(r["level"])]
    if not rules:
        return 0
    send, held = _notify_gate(event)
    if not send:
        return 0
    body = ["%s  ·  %s  ·  %s" % (ts, component, level),
            "Event: %s" % event,
            event_sentence(event, actor, detail, data)]
    if held:
        body.append("")
        body.append("%d further %s entr%s in the last few minutes were not "
                    "mailed - the notification bounds held them back. The "
                    "System Log has all of them."
                    % (held, event, "y" if held == 1 else "ies"))
    sent = 0
    for r in rules:
        if _send_mail(r["to"], "[Asset Manager] %s" % event, "\n".join(body)):
            sent += 1
    return sent
