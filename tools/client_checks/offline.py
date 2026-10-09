r"""The Storekeeper against a server that is not there: the offline buffer,
the flush, and the log of what was held.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import io
import json
import os

from client_checks.stage import (C, SB, SK, bad, close, eq, head, ok, quiesce,
                                 tk_or_skip)


def check_the_storekeeper_buffers_a_server_that_stopped_answering():
    """Unreachable is unreachable, whichever way requests spells it.

    _submit decided that from the exception class and named
    requests.exceptions.ConnectionError. ReadTimeout is not one - requests
    makes ConnectTimeout a ConnectionError, because it inherits from both, and
    leaves ReadTimeout outside it - so the one server state this system is
    built to survive, the socket accepted and the reply never coming, fell
    through to the generic handler. The storekeeper was shown "Lookup failed:
    ... Read timed out" and nothing was queued, on the one path where the
    movement has already happened and the record is owed.

    Both spellings are driven here rather than one, because what is being
    asserted is that the answer follows the situation and not the class: the
    server that never accepted and the server that accepted and went quiet are
    the same thing to somebody standing at the store with an asset in their
    hand.
    """
    head("the Storekeeper buffers a server that stopped answering")
    tk = tk_or_skip()
    if tk is None:
        return
    import requests

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    # showinfo and showerror block on a real Tk, so they are recorded instead.
    class _MB(object):
        def __init__(self):
            self.said = []

        def showinfo(self, title, msg=None, **kw):
            self.said.append(("info", title, msg))

        def showerror(self, title, msg=None, **kw):
            self.said.append(("error", title, msg))

        def showwarning(self, title, msg=None, **kw):
            self.said.append(("warn", title, msg))

        def askyesno(self, *a, **kw):
            return False

    real_mb, real_api, real_capi = SK.messagebox, SK.api, C.api
    # The lookup sheet is never consulted: the point is that the call raises.
    app.asset_types = ["Laptop"]

    def leg(label, ex):
        mb = _MB()
        SK.messagebox = mb

        def _raises(*_a, **_k):
            raise ex

        # GET /lookup now goes through common.lookup_asset() (141), so the
        # door has to be closed on both copies of the name.
        SK.api = C.api = _raises
        try:
            os.path.exists(SK.BUFFER_PATH) and os.remove(SK.BUFFER_PATH)
        except OSError:
            pass
        app.v_asset_no.delete(0, "end")
        app.v_asset_no.insert(0, "IT-0001")
        app.v_serial.delete(0, "end")
        app.v_member.set("Brian Dawson")
        app.v_direction.set("Out Store")
        app._submit()
        root.update_idletasks()
        root.update()

        held = []
        if os.path.exists(SK.BUFFER_PATH):
            held = json.loads(io.open(SK.BUFFER_PATH, encoding="utf-8").read())
        eq("%s: the Transaction is buffered" % label,
           [r.get("asset_number") for r in held], ["IT-0001"])
        eq("  and the storekeeper is told it was saved offline",
           bool(mb.said) and mb.said[-1][1], "Saved Offline")
        lookup_failed = [s for s in mb.said
                         if s[2] and "Lookup failed" in str(s[2])]
        eq("  and is not shown a failure instead", lookup_failed, [])

    try:
        # The one that shipped. Not a ConnectionError, and so not buffered.
        leg("a server that accepted and went quiet",
            requests.exceptions.ReadTimeout("read timed out"))
        # And the one that already worked, held to the same answer so the two
        # cannot drift apart again.
        leg("a server that never accepted",
            requests.exceptions.ConnectTimeout("connect timed out"))

        # So this cannot pass by finding a buffer that takes anything: a
        # refusal the server actually made is still a refusal, not a queue.
        mb = _MB()
        SK.messagebox = mb

        class _Refused(object):
            ok = False
            status_code = 400

            @staticmethod
            def json():
                return {"error": "nope"}

        SK.api = C.api = lambda *a, **k: _Refused()
        try:
            os.path.exists(SK.BUFFER_PATH) and os.remove(SK.BUFFER_PATH)
        except OSError:
            pass
        app.v_asset_no.delete(0, "end")
        app.v_asset_no.insert(0, "IT-0002")
        app.v_member.set("Brian Dawson")
        app._submit()
        root.update_idletasks()
        root.update()
        eq("an answer the server gave is not buffered",
           os.path.exists(SK.BUFFER_PATH), False)

        # ...except the one answer that is the server saying it is taking no
        # writes just now (G3, ADR-0018). The movement has already happened
        # and the record is owed, which is the offline buffer's situation
        # exactly - the only difference being that this server said so, which
        # is why the storekeeper is shown its words rather than ours.
        mb = _MB()
        SK.messagebox = mb

        class _Found(object):
            ok = True

            @staticmethod
            def json():
                return {"found": True, "asset_number": "IT-0003",
                        "serial_number": "", "asset_type": "Laptop"}

        class _Held(object):
            ok = False
            status_code = 503

            @staticmethod
            def json():
                return {"code": "maintenance",
                        "error": "The server is busy with a restore."}

        real_lookup = SK.lookup_asset
        SK.lookup_asset = lambda *a, **k: _Found()
        SK.api = C.api = lambda *a, **k: _Held()
        try:
            os.path.exists(SK.BUFFER_PATH) and os.remove(SK.BUFFER_PATH)
        except OSError:
            pass
        app.v_asset_no.delete(0, "end")
        app.v_asset_no.insert(0, "IT-0003")
        app.v_serial.delete(0, "end")
        app.v_member.set("Brian Dawson")
        app.v_direction.set("Out Store")
        try:
            app._submit()
            root.update_idletasks()
            root.update()
        finally:
            SK.lookup_asset = real_lookup

        held = []
        if os.path.exists(SK.BUFFER_PATH):
            held = json.loads(io.open(SK.BUFFER_PATH, encoding="utf-8").read())
        eq("a maintenance hold buffers the Transaction",
           [r.get("asset_number") for r in held], ["IT-0003"])
        eq("  and says it was saved for later rather than failed",
           bool(mb.said) and mb.said[-1][1], "Saved For Later")
        eq("  in the server's own words",
           "busy with a restore" in str(mb.said[-1][2] if mb.said else ""),
           True)
    finally:
        SK.messagebox, SK.api, C.api = real_mb, real_api, real_capi
        close(root, [])
        quiesce(root)
        try:
            root.destroy()
        except Exception:
            pass


def check_the_asset_types_cache_is_a_convenience_not_an_authority():
    """common.fetch_asset_types() and its on-disk cache (141).

    Rule 6 is enforced on the server regardless of what this returns - what is
    asserted here is only what a client shows while deciding what to offer in
    a Type dropdown, never whether a submit is accepted. A fetch that succeeds
    replaces the cache; one that fails - unreachable, or answering with no
    types in it - leaves the cache exactly as it was, the shape
    sync_server_cert already uses, so a stale answer is shown rather than the
    baked-in ASSET_TYPES falling back over the top of a real one. Only with
    nothing ever cached does a failure fall all the way back to ASSET_TYPES.
    """
    head("the asset types cache is a convenience, never an authority")
    real_api = C.api
    try:
        if os.path.exists(C.ASSET_CACHE_PATH):
            os.remove(C.ASSET_CACHE_PATH)

        eq("nothing cached yet falls back to the baked-in list",
           C.cached_asset_types(), C.ASSET_TYPES)

        class _Answer(object):
            def __init__(self, ok, types=None):
                self.ok = ok
                self._types = types

            def json(self):
                return {"asset_types": self._types}

        C.api = lambda *a, **k: _Answer(True, ["Laptop", "Router"])
        got = C.fetch_asset_types("http://server")
        eq("a fetch that succeeds returns the server's own list",
           got, ["Laptop", "Router"])
        eq("  and replaces the cache",
           C.cached_asset_types(), ["Laptop", "Router"])

        def _raises(*_a, **_k):
            raise OSError("client-checks: there is deliberately no server")
        C.api = _raises
        got = C.fetch_asset_types("http://server")
        eq("a fetch that fails returns the cache, not the baked-in fallback",
           got, ["Laptop", "Router"])
        eq("  and leaves the cache exactly as it was",
           C.cached_asset_types(), ["Laptop", "Router"])

        C.api = lambda *a, **k: _Answer(True, [])
        got = C.fetch_asset_types("http://server")
        eq("a fetch answering with no types also leaves the cache alone",
           (got, C.cached_asset_types()),
           (["Laptop", "Router"], ["Laptop", "Router"]))
    finally:
        C.api = real_api
        if os.path.exists(C.ASSET_CACHE_PATH):
            os.remove(C.ASSET_CACHE_PATH)


def check_the_offline_buffer_gives_up_on_a_permanent_refusal():
    """A queued Transaction the server will always refuse leaves the buffer.

    Neither a window check nor a static one. `_flush_buffer` counted every
    answer but 201 and 409 as "still offline" and put the payload back, so a
    400 was re-POSTed on every fifteen-second tick for the life of the
    installation: the movement never recorded, nothing saying so, and the
    storekeeper told at submit time that it would be sent when the server came
    back. No endpoint answers for that and no static read sees it - what is
    asserted here is which of three answers this app treats as permanent.

    The 400 it will actually meet is rule 6's. The offline path buffers before
    any lookup check, correctly, the Lookup Sheet being on the server - so an
    asset the sheet does not hold is the likeliest thing to be queued and
    always refused, which is the case the Tools tab's Propose an asset exists
    for.

    The server's own words are the other half of it. Only the server knows why
    it said no, and "failed" is the one answer nobody can act on.
    """
    head("the offline buffer gives up on a permanent refusal")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})

        def json(self):
            return self._body

    queued, shown = [], []
    real_api = SK.api
    root = None
    try:
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()

        # What the storekeeper is told is a notice on the window (#193),
        # so it is read here rather than off a `messagebox` stub. Wrapped
        # rather than replaced, since the strip is what is being claimed
        # to carry it and a stub that returned nothing would assert only
        # that the app called something.
        real_notice = app._notice

        def notice(level, title, lines):
            shown.append(" | ".join([title] + [l for l in lines if l]))
            return real_notice(level, title, lines)
        app._notice = notice

        def answer(*_a, **_k):
            nxt = queued.pop(0) if queued else _Answer(500)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        SK.api = answer

        def flush(payloads, answers):
            del shown[:]
            del queued[:]
            queued.extend(answers)
            app._buffer_save(payloads)
            app._flush_buffer()
            root.update_idletasks()
            return app._buffer_load()

        row = {"asset_number": "AM-404", "serial_number": "",
               "asset_type": "Laptop", "team_member": "Brian Dawson",
               "direction": "Out Store", "notes": "",
               "storekeeper": "Storekeeper User"}
        words = "Asset not in the lookup sheet: AM-404"

        left = flush([row], [_Answer(400, {"error": words,
                                           "code": "not_in_lookup"})])
        eq("a refusal leaves the buffer instead of being retried for ever",
           left, [])
        eq("  and the storekeeper is told, once", len(shown), 1)
        said = shown[0] if shown else ""
        eq("  in the server's own words", words in said, True)
        eq("  saying it was not recorded",
           "not recorded" in said.lower(), True)

        eq("a recorded one drains as it always did",
           (flush([row], [_Answer(201, {"id": 1})]), len(shown)), ([], 0))
        eq("so does one somebody has already recorded",
           (flush([row], [_Answer(409, {"error": "already pending"})]),
            len(shown)), ([], 0))
        eq("a 5xx is the server rather than the row, and stays queued",
           (flush([row], [_Answer(503)]), len(shown)), ([row], 0))
        eq("and so does an unreachable server, which is what this is for",
           (flush([row], [OSError("client-checks: no server")]), len(shown)),
           ([row], 0))

        other = dict(row, asset_number="AM-1")
        left = flush([row, other],
                     [_Answer(400, {"error": words}), _Answer(201, {"id": 2})])
        eq("one refusal does not take the row behind it down with it",
           (left, len(shown)), ([], 1))
    finally:
        SK.api = real_api
        if root is not None:
            root.destroy()
        if os.path.exists(SK.BUFFER_PATH):
            os.remove(SK.BUFFER_PATH)


def check_a_flush_asks_an_unreachable_server_once():
    """A flush against a server that is still down makes one attempt, not one
    per row.

    This loop is not on a worker: the whole background tick is an after()
    callback and runs straight through on the Tk thread, unlike the Notifier's,
    which is a worker. So every second it spends is a second the storekeeper's
    window cannot repaint in - and against a server that accepts and never
    answers, twenty queued rows were twenty five-second timeouts, a hundred
    seconds of a frozen app per fifteen-second tick. Nineteen of those requests
    could not come back with anything the first had not already said, being the
    same request to the same host a moment later.

    It is worst in the situation it exists for. The buffer only ever has rows in
    it because the server was unreachable, a bulk scan is what puts twenty in it
    at once, and a wedged-but-listening server is the state the rest of this
    system is explicitly built to survive - it is why `_port_in_use` probes with
    an exclusive bind rather than a connect and why the server runs threaded.

    What is measured is the **number of attempts**, which is the whole of the
    defect and is invisible in the buffer this leaves behind: the old loop and
    the new one both end with every row still queued. Beside it the half that
    keeps this honest - a server **answer** that is not 201/409 is about one row
    and must not stop the flush, so both a refusal and a 5xx have to leave the
    rows behind them attempted, or this would be asserting that a flush gives up
    on anything at all.
    """
    head("a flush asks an unreachable server once")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})

        def json(self):
            return self._body

    import requests

    tried, queued, shown = [], [], []
    real_api = SK.api
    root = None
    try:
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()

        # What the storekeeper is told is a notice on the window (#193),
        # so it is read here rather than off a `messagebox` stub. Wrapped
        # rather than replaced, since the strip is what is being claimed
        # to carry it and a stub that returned nothing would assert only
        # that the app called something.
        real_notice = app._notice

        def notice(level, title, lines):
            shown.append(" | ".join([title] + [l for l in lines if l]))
            return real_notice(level, title, lines)
        app._notice = notice

        def answer(_method, _url, *_a, **kw):
            tried.append((kw.get("json") or {}).get("asset_number"))
            nxt = queued.pop(0) if queued else _Answer(500)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        SK.api = answer

        rows = [{"asset_number": "AM-%d" % n, "serial_number": "",
                 "asset_type": "Laptop", "team_member": "Brian Dawson",
                 "direction": "Out Store", "notes": "",
                 "storekeeper": "Storekeeper User"} for n in range(1, 6)]

        def flush(payloads, answers):
            del tried[:]
            del queued[:]
            del shown[:]
            queued.extend(answers)
            app._buffer_save(payloads)
            app._flush_buffer()
            root.update_idletasks()
            return app._buffer_load()

        # A server that accepted and went quiet, which is what this is for.
        wedged = [requests.exceptions.ReadTimeout("no answer")] * 5
        left = flush(rows, wedged)
        eq("five queued rows against a wedged server are one attempt",
           len(tried), 1)
        eq("  and every row is still queued, in the order it was queued in",
           [r["asset_number"] for r in left],
           ["AM-1", "AM-2", "AM-3", "AM-4", "AM-5"])

        # A connection that was never accepted is the same answer to the same
        # question, so it ends the run the same way.
        left = flush(rows, [requests.exceptions.ConnectionError("no server")] * 5)
        eq("a server that refused the connection is one attempt too",
           (len(tried), len(left)), (1, 5))

        # What was already sent stays sent, and the rest keep their order.
        left = flush(rows, [_Answer(201, {"id": 1}),
                            requests.exceptions.ReadTimeout("no answer")])
        eq("a row sent before the server went is not re-queued",
           (len(tried), [r["asset_number"] for r in left]),
           (2, ["AM-2", "AM-3", "AM-4", "AM-5"]))

        # And the half that keeps it honest: an answer is about one row.
        left = flush(rows, [_Answer(400, {"error": "not in the lookup sheet"})]
                     + [_Answer(201, {"id": 2})] * 4)
        eq("a refusal does not stop the rows behind it being sent",
           (len(tried), left, len(shown)), (5, [], 1))

        left = flush(rows, [_Answer(503)] + [_Answer(201, {"id": 3})] * 4)
        eq("nor does a 5xx, which is the server answering about one row",
           (len(tried), [r["asset_number"] for r in left]), (5, ["AM-1"]))

        # And the one answer that does stop it (G3, ADR-0018), which is that
        # sentence rather than an exception to it: an ordinary 5xx is the
        # server failing at this row, where a `maintenance` 503 is the server
        # saying it is taking no writes at all - so it has already answered
        # for every row behind this one, exactly as a transport failure has.
        # Left to the branch above, a ten-minute restore would be forty POSTs
        # per fifteen-second tick on the Tk thread, which is the frozen window
        # this group exists to keep away, reached through a different door.
        held = _Answer(503, {"code": "maintenance",
                             "error": "The server is busy with a restore."})
        left = flush(rows, [held] * 5)
        eq("a maintenance hold is one attempt, like a transport failure",
           len(tried), 1)
        eq("  with every row still queued, in order",
           [r["asset_number"] for r in left],
           ["AM-1", "AM-2", "AM-3", "AM-4", "AM-5"])
        eq("  and nothing shown: the buffer is doing what it exists for",
           len(shown), 0)

        # The code and not the status: a 503 without it is somebody's proxy
        # answering about this one request, which is the assertion four lines
        # up and must go on holding.
        left = flush(rows, [_Answer(503, {"error": "Bad Gateway"})]
                     + [_Answer(201, {"id": 4})] * 4)
        eq("a 503 carrying no code is still the per-row answer",
           (len(tried), [r["asset_number"] for r in left]), (5, ["AM-1"]))
    finally:
        SK.api = real_api
        if root is not None:
            root.destroy()
        if os.path.exists(SK.BUFFER_PATH):
            os.remove(SK.BUFFER_PATH)


def check_the_storekeeper_logs_what_it_buffered():
    """A Transaction queued offline is one entry, whichever leg queued it.

    The entry belonged to the caller and only one of the two callers had it.
    The POST leg of _submit - the server falling over inside the few hundred
    milliseconds between the lookup and the submit - wrote
    transaction.buffered; the lookup leg, which is what happens every time the
    server is simply down, wrote nothing at all. So the one entry that only
    ever exists when the server cannot be reached was missing from the path
    the offline buffer exists for.

    Both halves of this app's System Log are read back, because the entry was
    missing from both and they answer different questions: the shipping queue
    is the copy the Admin reads, where all three components sit on one
    timeline, and client.log is what this machine can still say about itself
    when the server cannot be reached - which is the situation being logged.

    Both legs are driven rather than the one that was broken, because what is
    asserted is that a buffered Transaction is logged and not which except
    caught it. Beside them a refusal the server actually made, which is
    neither buffered nor logged as buffered, so this cannot pass by finding a
    log that records everything.
    """
    head("the Storekeeper logs what it buffered")
    tk = tk_or_skip()
    if tk is None:
        return
    import requests

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    # showinfo and showerror block on a real Tk, so they are recorded instead.
    class _MB(object):
        def __init__(self):
            self.said = []

        def showinfo(self, title, msg=None, **kw):
            self.said.append(("info", title, msg))

        def showerror(self, title, msg=None, **kw):
            self.said.append(("error", title, msg))

        def showwarning(self, title, msg=None, **kw):
            self.said.append(("warn", title, msg))

        def askyesno(self, *a, **kw):
            return False

    real_mb, real_api, real_capi = SK.messagebox, SK.api, C.api
    app.asset_types = ["Laptop"]

    def submit(stub, asset_no):
        """One Submit against `stub`, with both halves of the log emptied first."""
        SK.messagebox = _MB()
        # GET /lookup now goes through common.lookup_asset() -> common.api
        # (141), so both copies of the name have to answer the same way.
        SK.api = C.api = stub
        try:
            os.path.exists(SK.BUFFER_PATH) and os.remove(SK.BUFFER_PATH)
        except OSError:
            pass
        with C._log_lock:
            del C._log_queue[:]
        io.open(C.LOG_PATH, "w", encoding="utf-8").close()
        app.v_asset_no.delete(0, "end")
        app.v_asset_no.insert(0, asset_no)
        app.v_serial.delete(0, "end")
        app.v_member.set("Brian Dawson")
        app.v_direction.set("Out Store")
        app._submit()
        root.update_idletasks()
        root.update()
        held = []
        if os.path.exists(SK.BUFFER_PATH):
            held = json.loads(io.open(SK.BUFFER_PATH, encoding="utf-8").read())
        with C._log_lock:
            # Only this app's Transaction events: app.started is written in
            # __init__ and would answer for an entry this never wrote.
            shipped = [e for e in C._log_queue
                       if e["event"].startswith("transaction.")]
        written = [l for l in io.open(C.LOG_PATH, encoding="utf-8")
                   if "transaction." in l]
        return held, shipped, written

    class _Found(object):
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"found": True, "asset_number": "IT-0001",
                    "serial_number": "", "asset_type": "Laptop"}

    def unreachable(*_a, **_k):
        raise requests.exceptions.ConnectionError("no server")

    def answered_then_gone(method, _url, *_a, **_k):
        # The lookup gets through and the submit does not, which is the leg
        # that was already logging: held to the same entry, not the same path.
        if method == "get":
            return _Found()
        raise requests.exceptions.ConnectionError("no server")

    def leg(label, stub):
        held, shipped, written = submit(stub, "IT-0001")
        eq("%s: the Transaction is buffered" % label,
           [r.get("asset_number") for r in held], ["IT-0001"])
        eq("  and one transaction.buffered entry is shipped to the server",
           [e["event"] for e in shipped], ["transaction.buffered"])
        eq("  and one is in this machine's own client.log", len(written), 1)
        detail = shipped[0]["detail"] if shipped else ""
        eq("  naming the asset, the Engineer and the direction",
           [s for s in ("IT-0001", "Brian Dawson", "Out Store")
            if s not in detail], [])
        eq("  at warn, attributed to the Storekeeper",
           [shipped[0]["level"], shipped[0]["actor"]] if shipped else [],
           ["warn", SK.sk_actor()])

    try:
        # The one that was silent: the server was already down when Submit
        # was pressed, which is the whole situation the buffer exists for.
        leg("a server that was already down", unreachable)
        # And the one that was not, held to the same entry.
        leg("a server that went between the lookup and the submit",
            answered_then_gone)

        class _Refused(object):
            ok = False
            status_code = 400

            @staticmethod
            def json():
                return {"error": "not in the lookup sheet"}

        def refused(method, _url, *_a, **_k):
            return _Found() if method == "get" else _Refused()

        held, shipped, written = submit(refused, "IT-0002")
        eq("an answer the server gave is not buffered", held, [])
        eq("  and is logged as refused rather than buffered",
           [e["event"] for e in shipped], ["transaction.refused"])
    finally:
        SK.messagebox, SK.api, C.api = real_mb, real_api, real_capi
        close(root, [])
        quiesce(root)


def check_a_bulk_submit_logs_every_transaction_it_sends():
    """One entry per Transaction, in the two shapes the form already writes.

    `_submit` writes a System Log entry for every answer it gets and
    `_bulk_submit_all` wrote none, so twenty assets scanned in one sitting were
    twenty rows in `transactions` and nothing in either half of this
    installation's log - while the same twenty typed one at a time through the
    form were twenty entries in each. The path that carries the volume was the
    invisible one, which is why the log read as though this store only ever
    submits one asset at a time.

    The refusals are the half that costs an Admin something concrete: a bulk row
    the server turned down is a message box that is dismissed and gone, and
    `transaction.refused` is the only durable record that it was attempted at
    all - the entry somebody goes looking for when an asset turns out never to
    have been recorded.

    **One entry per Transaction, not one per batch.** A batch is not a thing the
    `transactions` table has: `_create_transaction` writes a row per asset, and
    `asset_proposals` is the one place in this system where a batch is a fact
    at all, derived there from a shared `proposed_at` rather than stored. So a
    summary line would be a second shape for the same act with nothing to join
    it to - which is why the stub below takes some rows and refuses others
    inside **one** call, rather than driving a batch of one twice.

    Both halves of the log are read back, for the reason the group above gives:
    the shipping queue is the copy the Admin reads and `client.log` is what this
    machine can still say about itself. And the 409 is asserted as the entry
    that is deliberately **not** written, since `_submit` writes none for one
    either - a Transaction somebody has already recorded - so this cannot pass
    by finding a loop that logs whatever it touches.
    """
    head("a bulk submit logs every Transaction it sends")
    tk = tk_or_skip()
    if tk is None:
        return

    class _MB(object):
        def __init__(self):
            self.said = []

        def showinfo(self, title, msg=None, **kw):
            self.said.append(("info", title, msg))

        def showerror(self, title, msg=None, **kw):
            self.said.append(("error", title, msg))

        def showwarning(self, title, msg=None, **kw):
            self.said.append(("warn", title, msg))

    class _Answer(object):
        def __init__(self, status, payload):
            self.status_code = status
            self.ok = status < 400
            self._payload = payload

        def json(self):
            return self._payload

    # One call, four rows, three different answers: two taken, one refused by
    # the sheet and one already pending. The queue order is the order the loop
    # walks, so the entries can be read back positionally.
    ANSWERS = {
        "IT-0001": _Answer(201, {"status": "created"}),
        "IT-0002": _Answer(400, {"error": "not in the lookup sheet",
                                 "code": "not_in_lookup"}),
        "IT-0003": _Answer(201, {"status": "created"}),
        "IT-0004": _Answer(409, {"error": "already has a pending transaction"}),
    }

    def stub(method, _url, *_a, **kw):
        if method != "post":
            raise OSError("client-checks: there is deliberately no server")
        return ANSWERS[(kw.get("json") or {}).get("asset_number")]

    root = tk.Tk()
    root.geometry("1360x830+0+0")
    app = SK.StorekeeperApp(root)
    root.update_idletasks()
    root.update()

    real_mb, real_api = SB.messagebox, SB.api
    mb = _MB()
    try:
        app._bulk.open()
        root.update_idletasks()
        root.update()
        app._bulk._bulk_queue[:] = [
            {"asset_number": n, "serial_number": "", "asset_type": "Laptop",
             "asset_model": "T14", "scanned": n, "known": True}
            for n in ("IT-0001", "IT-0002", "IT-0003", "IT-0004")]
        app._bulk._bulk_paint()
        app._bulk._bulk_member.set("Brian Dawson")
        app._bulk._bulk_direction.set("Out Store")

        with C._log_lock:
            del C._log_queue[:]
        io.open(C.LOG_PATH, "w", encoding="utf-8").close()

        SB.messagebox, SB.api = mb, stub
        app._bulk._bulk_submit_all()
        root.update_idletasks()
        root.update()
    finally:
        SB.messagebox, SB.api = real_mb, real_api

    with C._log_lock:
        shipped = [e for e in C._log_queue
                   if e["event"].startswith("transaction.")]
    written = [l for l in io.open(C.LOG_PATH, encoding="utf-8")
               if "transaction." in l]

    eq("each row the server answered for is its own entry",
       [e["event"] for e in shipped],
       ["transaction.submitted", "transaction.refused",
        "transaction.submitted"])
    eq("  and this machine's own client.log holds the same three",
       len(written), 3)
    eq("  with nothing written for the 409, which _submit does not log either",
       [e for e in shipped if "IT-0004" in e["detail"]], [])

    for e in shipped:
        if e["event"] != "transaction.submitted":
            continue
        eq("  a submitted entry names the asset, the Engineer and the direction",
           [s for s in (e["detail"].split()[0], "Brian Dawson", "Out Store")
            if s not in e["detail"]], [])
        eq("  at info, attributed to the Storekeeper",
           [e["level"], e["actor"]], ["info", SK.sk_actor()])

    refused = [e for e in shipped if e["event"] == "transaction.refused"]
    eq("the refusal is one entry at warn, attributed the same way",
       [[r["level"], r["actor"]] for r in refused],
       [["warn", SK.sk_actor()]])
    eq("  naming the asset and the server's own words",
       [s for s in ("IT-0002", "not in the lookup sheet")
        if s not in (refused[0]["detail"] if refused else "")], [])

    # And that the log agrees with what the window said it did, which is the
    # other direction of the same fact.
    told = " ".join(str(m) for _k, _t, m in mb.said)
    if "2 submitted" in told:
        ok("and the window reported the two the log records")
    else:
        bad("the window reported something other than the two submitted "
            "entries the log holds: %r" % told[:160])

    close(root, [])
    quiesce(root)


def check_a_bulk_row_the_server_never_answered_is_buffered():
    """A bulk submission against a server that is not there is written down.

    `_submit` buffers a Transaction the server could not answer;
    `_bulk_submit_all` kept it in `self._bulk_queue`, a plain list on the app
    object that nothing in that file ever writes anywhere. The window's own
    comment - "Rows survive the window being closed and reopened" - is true and
    is the whole of it: they did not survive the app being closed. So forty
    assets scanned and handed over against a server that is not there were forty
    movements in RAM, reported as *still in the list*, and gone with the process,
    with no file to flush and nothing saying they had ever been owed.

    The movement already happened and the record is owed, which is the offline
    buffer's whole argument, and the payload this loop builds has the same keys
    in the same shape as `_buffer_offline_submit`'s, so `_flush_buffer` sends it
    unchanged. **Not the proposals' answer**: a proposal is refused rather than
    queued because it is a question, and a queued question is one the
    storekeeper believes was asked (ADR-0012).

    Driven rather than read, because what is asserted is where the rows end up
    across two places at once - out of the queue, so a second click cannot send
    them twice, and into the file. The positive half is a refusal the server
    actually made, which must **not** be buffered, so this cannot pass by
    finding a path that buffers anything it touches.
    """
    head("a bulk row the server never answered is buffered")
    tk = tk_or_skip()
    if tk is None:
        return
    import requests

    class _MB(object):
        def __init__(self):
            self.said = []

        def showinfo(self, title, msg=None, **kw):
            self.said.append(msg)

        def showerror(self, title, msg=None, **kw):
            self.said.append(msg)

        def showwarning(self, title, msg=None, **kw):
            self.said.append(msg)

    class _Answer(object):
        def __init__(self, status, payload=None):
            self.status_code, self._payload = status, (payload or {})
            self.ok = status < 400

        def json(self):
            return self._payload

    real_mb, real_api = SB.messagebox, SB.api
    root = None
    try:
        root = tk.Tk()
        root.geometry("1360x830+0+0")
        app = SK.StorekeeperApp(root)
        root.update_idletasks()
        root.update()
        app._bulk.open()
        root.update_idletasks()
        root.update()

        def bulk(names, stub):
            if os.path.exists(SK.BUFFER_PATH):
                os.remove(SK.BUFFER_PATH)
            mb = _MB()
            app._bulk._bulk_queue[:] = [
                {"asset_number": n, "serial_number": "", "asset_type": "Laptop",
                 "asset_model": "T14", "scanned": n, "known": True}
                for n in names]
            app._bulk._bulk_paint()
            app._bulk._bulk_member.set("Brian Dawson")
            app._bulk._bulk_direction.set("Out Store")
            SB.messagebox, SB.api = mb, stub
            try:
                app._bulk._bulk_submit_all()
            finally:
                SB.messagebox = real_mb
            root.update_idletasks()
            root.update()
            return app._buffer_load(), " ".join(str(s) for s in mb.said)

        def unreachable(*_a, **_k):
            raise requests.exceptions.ConnectionError("no server")

        held, told = bulk(["AM-1", "AM-2", "AM-3"], unreachable)
        eq("three rows against a server that is not there are three buffered",
           [r.get("asset_number") for r in held], ["AM-1", "AM-2", "AM-3"])
        eq("  carrying the Engineer and the direction the window was set to",
           sorted({(r.get("team_member"), r.get("direction")) for r in held}),
           [("Brian Dawson", "Out Store")])
        eq("  and out of the queue, so a second click cannot send them twice",
           app._bulk._bulk_queue, [])
        if "saved offline" in told:
            ok("and the report says they were saved rather than still listed")
        else:
            bad("the report still says the rows are in the list: %r"
                % told[:200])

        # The positive half: an answer the server gave is about that row and is
        # not a reason to buffer anything.
        def refused(_method, _url, *_a, **_k):
            return _Answer(400, {"error": "not in the lookup sheet",
                                 "code": "not_in_lookup"})

        held, told = bulk(["AM-9"], refused)
        eq("a refusal the server made is not buffered", held, [])
        eq("  and the row stays in the list to be acted on",
           [i["asset_number"] for i in app._bulk._bulk_queue], ["AM-9"])
    finally:
        SB.messagebox, SB.api = real_mb, real_api
        if root is not None:
            close(root, [])
            quiesce(root)
        if os.path.exists(SK.BUFFER_PATH):
            os.remove(SK.BUFFER_PATH)
