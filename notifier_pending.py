"""
Asset Manager — the Notifier's Pending decisions

What a Confirm or a Reject means, what becomes of an answer the server would
not take, and which Pending Transaction is offered next. **No tkinter here,
and nothing that opens a socket**: every function below takes what it is given
and answers with what should happen, and `notifier_app.py` performs it.

That split is #208. Until it, all of this lived inside Tk callbacks -
`_confirm` and `_reject` called `_send_answer`, which performed the request and
mutated the pending queue in one act - so the only way to assert any of it was
to open a real window and measure it. `docs/CODING_STANDARDS.md` records what
that costs: #204 ran one unchanged group three times for green, red, green and
read 67, 64, 60, 58 and 56px on different runs, and the **green** runs were the
wrong ones, hiding a real clipped control. `tools/client-checks.py` drives this
module with no root window and no display at all; if a check here ever needs
one, the seam is in the wrong place.

Two things stay in `notifier_app.py` on purpose:

- **The request.** `request()` says where an answer goes and `classify()` reads
  what came back, but the call between them is the app's. This module imports
  no transport and holds no server URL - that address can change under a
  running Notifier (the port-change cascade), and a second copy of it here
  would be one more thing to keep in step.
- **The System Log event names.** `note()` decides what a line says; the name
  beside it is written at the call site, because `tools/cascade-audit.py` reads
  those names out of `log_event(...)` calls to hold `docs/system-log-events.md`
  and `EVENT_SENTENCES` honest. A name reached only through a variable would be
  a documented event the audit reports as emitted by nothing.

**Not a race fix.** The review that filed #208 first flagged the Notifier's
command queue as unsafe across threads. It is not, and nothing here was written
to make it so - see `notifier_app._drain_commands`.
"""
import time
from collections import namedtuple

# `held_for_maintenance` and `maintenance_notice` read a reply object and
# nothing else - no request, no socket, no path - so `classify` calls them here
# rather than making the app pre-digest an answer it would only hand back.
import common

# The two answers an engineer can give. Strings rather than an enum because
# they are also the wire's own words: an entry held in `pending_answers.json`
# carries one of them, and a buffer written by an older build has to read back.
CONFIRM = "confirm"
REJECT = "reject"

# What one attempt at delivering an answer came to. `HOLD` is the only one that
# keeps the entry: `SENT` is done with, and `REFUSED` is permanent for the
# reason the Storekeeper's offline buffer gives up on a 4xx - a payload the
# server will always refuse, retried every fifteen seconds, is a queue that
# never empties and never says so.
SENT, HOLD, REFUSED = "sent", "hold", "refused"


# ─── One answer ───────────────────────────────────────────────────────────────

def confirm(tid):
    """The engineer confirmed Transaction `tid`."""
    return {"action": CONFIRM, "id": tid}


def reject(tid, reason=""):
    """The engineer rejected Transaction `tid`, with their reason."""
    return {"action": REJECT, "id": tid, "reason": reason}


def request(entry):
    """Where one answer goes and what it carries: `(path, payload)`.

    A path rather than a URL, for the reason in this module's docstring.
    `payload` is None where there is no body, which a Confirm has none of - the
    id in the path is the whole of it.
    """
    tid = entry.get("id")
    if entry.get("action") == REJECT:
        return "/reject/%s" % tid, {"reason": entry.get("reason", "")}
    return "/confirm/%s" % tid, None


def classify(reply):
    """What one attempt came to: `(outcome, why)`.

    `reply` is whatever the request answered with, or **None** for a request
    that raised - no server there, a name that would not resolve, a timeout.

    **409 is `SENT`**, not refused: `not_pending` is the server saying this
    Transaction is already resolved, which is the same answer the Storekeeper's
    flush treats as done - somebody has the record, and asking again would only
    ever get it back.

    A 4xx is **permanent** and leaves the queue, for the reason stated beside
    `REFUSED` above. Everything else is held: a maintenance hold, an ordinary
    5xx and a server that is not there are one situation from here, which is
    that the answer has not been recorded yet.
    """
    if reply is None:
        return HOLD, ""
    if reply.status_code in (200, 201, 409):
        return SENT, ""
    if common.held_for_maintenance(reply):
        return HOLD, common.maintenance_notice(reply)
    if 400 <= reply.status_code < 500:
        try:
            why = (reply.json() or {}).get("error") or ""
        except Exception:
            why = ""
        return REFUSED, why or ("The server refused it (%d)."
                                % reply.status_code)
    return HOLD, ""


def held(entry, outcome, why):
    """The entry to keep until the server will take it, or None.

    Held rather than lost on `HOLD` alone. An engineer's answer that never
    reached the server leaves a Pending Transaction the **24h Auto-Accept**
    resolves a day later with nobody having said yes - which happens to agree
    with a Confirm and is the exact opposite of a Reject, and is an answer
    nobody gave either way.
    """
    return dict(entry, why=why) if outcome == HOLD else None


def note(entry):
    """What the System Log line about this answer says.

    The event name is the caller's, for the reason in this module's docstring.
    A Reject carries the reason because that is the half an Admin reading two
    disagreeing records needs; a Confirm has nothing to add to the id.
    """
    if entry.get("action") == REJECT:
        return "#%s  %s" % (entry.get("id"),
                            entry.get("reason") or "(no reason given)")
    return "#%s" % entry.get("id")


# ─── The offline hold ─────────────────────────────────────────────────────────

def merge(items, entry):
    """The held queue with `entry` as the only answer about its Transaction.

    One entry per Transaction: an engineer cannot answer the same one twice
    from the popup - it closes on the first - and a queue holding a Confirm and
    a Reject for one id would be two answers the server takes in whatever order
    they happened to be written.

    Compared as strings, the ids in a buffer written by an older build having
    been through JSON.
    """
    kept = [e for e in items if str(e.get("id")) != str(entry.get("id"))]
    return kept + [entry]


class Flush(object):
    """One pass over the held answers. The caller performs each attempt.

        run = Flush(items)
        entry = run.next()
        while entry is not None:
            run.took(*send(entry))
            entry = run.next()

    **One hold ends the run**, the rule the Storekeeper's flush keeps and for
    the same reason turned around: the answer that could not be delivered has
    been given about the *server* rather than about this row, so every entry
    behind it would get it too - and this loop runs on the poll worker, where
    each attempt is a timeout the next poll waits for.

    A refusal leaves the queue and is collected in `refused` for the caller to
    write down. Nothing is shown for one: the engineer answered this
    Transaction minutes or days ago and a popup about it now would be about a
    window they no longer have in front of them, where the System Log is read
    by the Admin who has to work out why a Transaction says one thing and an
    engineer says another.
    """

    def __init__(self, items):
        self._items = list(items)
        self._at = 0
        self._stopped = False
        self.refused = []      # (entry, why) - left the queue, worth a line
        self.held = ""         # the server's words, if it stopped taking them

    def next(self):
        """The next answer to try, or None when the run is over."""
        if self._stopped or self._at >= len(self._items):
            return None
        return self._items[self._at]

    def took(self, outcome, why):
        """What the attempt `next()` handed out came to."""
        if outcome == HOLD:
            self._stopped = True
            self.held = why
            return
        if outcome == REFUSED:
            self.refused.append((self._items[self._at], why))
        self._at += 1

    def remaining(self):
        """What is still owed, in the order it was queued in."""
        return self._items[self._at:]


# ─── The order they are offered in ────────────────────────────────────────────

def left_pending(row):
    """The notice for a Transaction answered somewhere other than this popup.

    `row` is its row from the history, or None where that could not be read.
    An answer given anywhere other than this popup is "Answered elsewhere"
    (#284).
    """
    return "Answered elsewhere"


def waiting(rows, member, busy=()):
    """This Engineer's Pending Transactions, in the order they are offered.

    The window's half of the order; `PopupQueue` below is the tray's. They are
    in one module rather than one function because they are two orders on
    purpose, and the pair being written down together is what stops either
    becoming a second answer to the other's question:

    - **The window lists newest first.** It is a list, and every list in this
      product reads newest first; the deadline each row is against is on the
      row.
    - **The tray offers oldest first**, which is the order `GET /pending`
      hands them over in (`ORDER BY timestamp`). A popup asks about one
      Transaction and then goes away, so the one worth asking about first is
      the one closest to the 24h Auto-Accept.

    `member` is matched **without regard to case**, the way the server matches
    the column it filters on: the name is a label carrying whatever spelling
    was written at the time, and this Engineer is the same person under any of
    them. A mis-cased configured name used to empty this queue silently, which
    is an Engineer who stops being asked to confirm anything.

    `busy` is the ids already answered in this window and not yet gone from the
    server's answer, so a second click cannot send a second confirmation.

    **This Engineer's own, whatever `view_all_history` says.** That permission
    widens what they may *see*; the queue is what they are offered to act on,
    and the server accepts a confirmation from anybody, deliberately and
    permanently (ADR-0002) - so a row belonging to somebody else, offered here,
    is an Engineer resolving a Transaction nobody asked them about.
    """
    mine = (member or "").casefold()
    out = [r for r in rows
           if not r.get("confirmed") and not r.get("rejected")
           and not r.get("cancelled")
           and (r.get("team_member") or "").casefold() == mine
           and r.get("id") not in busy]
    # Sorted here rather than relying on what the caller was handed: the
    # window's rows come from `GET /transactions` and the tray's from
    # `GET /pending`, and those two do not agree about the order.
    out.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    return out


# ─── The order the popups are drained in ──────────────────────────────────────

# What `PopupQueue.next()` answers with. `queued` is how many are behind the one
# being shown, which is the "N more waiting" the popup prints; `wait_ms` is how
# long until it is worth asking again. Each is zero in the answers it is not
# about, rather than None, so a caller reading the wrong one gets a number it
# can pass to a timer instead of a TypeError on the Tk thread.
Next = namedtuple("Next", "kind tx queued wait_ms")

SHOW, WAIT, IDLE = "show", "wait", "idle"


class PopupQueue(object):
    """Which Pending Transaction is offered next, and when.

    No tkinter and no timer of its own: `next()` answers "show this one",
    "come back in N ms" or "nothing to do", and the caller arms whatever clock
    it has. `now` is injected so a check can drive a gap without waiting one
    out.

    It holds the two facts that have to agree - the queue, and the ids this
    process has already offered. A Transaction in `seen` is never queued again
    by a later poll, which is what makes losing one from `queue` without
    dropping it from `seen` an engineer who is simply never asked again.
    """

    def __init__(self, repeat_ms, now=time.monotonic):
        self.queue = []        # Transactions waiting to be shown, in order
        self.seen = set()      # ids this process has already offered
        self.repeat_ms = repeat_ms
        # Nothing is shown before this (`now()`). It is what a deferral sets,
        # and it is a deadline rather than a flag because the poll worker asks
        # for the next popup whenever new Pending Transactions arrive - which
        # would otherwise put the deferred one straight back up and make the
        # gap nothing at all.
        self.hold_until = 0.0
        self._now = now

    def arrived(self, pending):
        """The Transactions in `pending` nobody has been asked about yet.

        Queued in place rather than by rebuilding the list: the caller's Tk
        thread strips answered ids out of the same list, and a rebuild landing
        on the list that had just been replaced would be a Transaction nobody
        is ever asked about.
        """
        new = [t for t in pending if t["id"] not in self.seen]
        for t in new:
            self.seen.add(t["id"])
            self.queue.append(t)
        return new

    def next(self):
        """`SHOW` with the Transaction, `WAIT` with a delay, or `IDLE`.

        A deferred popup is waiting out its gap, and so is everything queued
        behind it (#194): it went back to the **front**, having not been
        answered, so what is at the head is the Transaction whose gap this is.

        `WAIT` rather than `IDLE` while the gap is open, deliberately: the
        caller is woken by a timer armed for exactly that moment, and Tk's
        `after` runs off the Windows timer rather than off `time.monotonic` -
        measured firing up to 13ms early against it - so a wake is routinely a
        hair in front of the deadline it compares to. Answering `IDLE` then
        would drop the Transaction for the life of the process: it is already
        in `seen`, so no later poll puts it back, and the engineer is never
        asked again, which is the one failure #194 must not be able to cause.
        """
        if not self.queue:
            return Next(IDLE, None, 0, 0)
        left = self.hold_until - self._now()
        if left > 0:
            return Next(WAIT, None, len(self.queue), max(1, int(left * 1000) + 2))
        tx = self.queue.pop(0)
        return Next(SHOW, tx, len(self.queue), 0)

    def deferred(self, tx):
        """A popup left the screen unanswered (#194, #201). Returns the gap, ms.

        Front of the queue, because it has not been answered and the
        Transactions behind it have not been asked about yet - so the engineer
        is offered this one again before any of them, which is the order they
        arrived in.
        """
        self.queue.insert(0, tx)
        self.hold_until = self._now() + self.repeat_ms / 1000.0
        return self.repeat_ms

    def departed(self, pending, shown=None):
        """Ids this process is holding that `pending` no longer lists (#284).

        Held is the queue - a popup deferred by #194 is back at its front, so
        it is covered - and `shown`, the id of the popup on screen, which is
        in neither. Each is `resolved` here, so a deferred popup that left
        Pending is dropped rather than re-shown. The caller closes the popup
        on screen and says where the answer was given.
        """
        live = set(t["id"] for t in pending)
        held = [t.get("id") for t in self.queue]
        if shown is not None:
            held.append(shown)
        gone = [tid for tid in held if tid not in live]
        for tid in gone:
            self.resolved(tid)
        return gone

    def resolved(self, tid):
        """This Transaction is answered: stop offering it, and stop asking.

        Both halves, because they are one fact. Removed from the queue one at a
        time rather than by rebuilding it, for the reason `arrived` appends in
        place.
        """
        self.seen.discard(tid)
        for t in [t for t in self.queue if t.get("id") == tid]:
            try:
                self.queue.remove(t)
            except ValueError:
                pass

    def forget(self):
        """Ask again about everything the server still calls Pending.

        What a settings change and a Log off do - a Notifier pointed at
        another server or logged on as another engineer has been told nothing
        about what it already showed.
        """
        self.seen.clear()
