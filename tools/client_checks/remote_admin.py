r"""The Notifier's Remote Admin console (#218): what a capability password
opens, and the panels behind it.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
from client_checks.stage import (NR, bad, eq, head, measure,
                                 measure_scrolled_body, ok, quiesce,
                                 scroll_reaches_its_form,
                                 survives_a_short_screen, tk_or_skip)


def check_the_notifier_remote_admin_shows_only_what_the_password_opens():
    """What a capability password opens, asked by knocking rather than told.

    R2. There is deliberately no endpoint that answers "what does this
    password open?" - a route naming a capability would be a way to read the
    delegation map over the wire, and `server-checks.py` asserts that none
    does. So this window learns it the only way there is: each door authorises
    **before** it looks at the body, so each is knocked on with a body it is
    going to turn down, and a 400 is the door having opened while a 401 is the
    credential being refused.

    **Six doors since #174**, and two of them were chosen rather than
    found: `POST /members/rename` with no id authorises first and cannot write
    a row, where `POST /members` would add an Engineer every time somebody
    opened this window, and `POST /assets/proposals/decide` with no id is that
    same shape - `POST /assets/propose` would file a proposal on every unlock,
    and `GET /assets/proposals` beside it needs no credential at all, so it
    would answer for any password and say nothing about whether that one may
    decide. Both are asserted here as well as written down in the probe - the
    paths are one word apart in a stub table, so a knock moved onto a writing
    door has to be moved here deliberately.

    The sixth is `GET /clients` (#174), and it is the third knock that is not
    one - a plain read the panel behind it needs anyway, like Host & Port and
    Mail. What makes it usable as a knock at all is that the registry is
    **never open**: it is the map of hostnames, Windows account names and
    addresses of machines on the internal network, so unlike
    `GET /assets/proposals` one door up it answers who is asking rather than
    answering anybody.

    None of that is reachable from a static read, and none of it from a live
    server either - what is being asserted is which panels a *particular*
    answer produces, which means stubbing the answer. So `api` is replaced per
    path and the window is driven through its own unlock.

    The fourth leg is the one with nothing to show for itself: a password that
    opens **nothing** is refused as a password, on the form, rather than by
    opening an empty window. An empty window reads as a server with nothing in
    it, where the truth is that this credential reaches none of it - and the
    two ways that happens need different things done about them, a credential
    that opens no door and a channel that is not HTTPS, so the server's own
    sentence is what gets shown.
    """
    head("the Notifier's Remote Admin shows only what the password opens")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})
            self.ok = 200 <= status < 300

        def json(self):
            return self._body

    def answering(table):
        """`api` answering per path, out of {path fragment: _Answer}."""
        def _api(method, url, **kw):
            for frag, answer in table.items():
                if frag in url:
                    return answer
            raise AssertionError("no stub for " + url)
        return _api

    OPEN_CFG = _Answer(200, {"host": "0.0.0.0", "port": 8081})
    SHUT_CFG = _Answer(401, {"error": "Wrong password.", "code":
                             "bad_password"})
    OPEN_POST = _Answer(400, {"error": "No record ids provided"})
    OPEN_NAME = _Answer(400, {"error": "No Engineer id provided",
                              "code": "no_id"})
    SHUT_POST = _Answer(401, {"error": "Wrong password.", "code":
                              "bad_password"})
    INSECURE = _Answer(403, {"error": "A capability password needs HTTPS.",
                             "code": "insecure"})
    # What the Engineers panel reads once it is drawn. `GET /permissions` needs
    # no credential - rule 8 keeps the captions in `server.py` and lets no
    # client carry a copy - and `GET /members` never did.
    # The Mail door answers a read rather than a refusal, which is what
    # makes its knock the panel's own load (#172).
    # The Asset Proposals door is `POST /assets/proposals/decide` with no
    # id, which is a knock of the first kind and has to be: `GET
    # /assets/proposals` beside it needs no credential at all, so it would
    # answer for any password and say nothing about whether that one may
    # decide (#173).
    OPEN_PROP = _Answer(400, {"error": "A proposal id is required.",
                              "code": "no_id"})
    SHUT_PROP = _Answer(401, {"error": "Wrong password.", "code":
                              "bad_password"})
    PROPOSALS = _Answer(200, [
        {"id": 7, "asset_number": "P-1", "serial_number": "PS-1",
         "asset_type": "Screen", "asset_model": "U2419H",
         "proposed_by": "Storekeeper User (Storekeeper)",
         "proposed_at": "2026-02-03T09:00:00", "status": "pending"}])
    # The Connected Clients door is `GET /clients`, which answers the panel
    # its own load and is never open (#174).
    OPEN_CLIENTS = _Answer(200, {
        "clients": [{"client_id": "c-1", "hostname": "HOST-L14",
                     "app": "Notifier", "version": "2.3.0",
                     "member": "Brian Dawson", "os_user": "bdawson",
                     "address": "192.0.2.12", "cert_fingerprint": "AA:BB",
                     "last_seen": "2026-02-03T09:00:00", "age_secs": 30,
                     "commands": []}],
        "served": "AA:BB", "staged": ""})
    SHUT_CLIENTS = _Answer(401, {"error": "Wrong password.", "code":
                                 "bad_password"})
    OPEN_MAIL = _Answer(200, {"host": "relay.example", "port": 25,
                              "from": "assets@example", "username": "",
                              "starttls": True, "password_stored": True,
                              "can_store": True})
    SHUT_MAIL = _Answer(401, {"error": "Wrong password.", "code":
                              "bad_password"})
    PERMS = _Answer(200, [{"name": "view_all_history",
                           "label": "Sees every Engineer's history"}])
    MEMBERS = _Answer(200, [
        {"id": 1, "name": "Brian Dawson", "auto_approve": False,
         "profile": "default", "permissions": [], "has_password": True,
         "must_change_password": True},
        {"id": 2, "name": "Carol Evans", "auto_approve": True,
         "profile": "custom", "permissions": ["view_all_history"],
         "has_password": False, "must_change_password": False}])

    root = tk.Tk()
    root.withdraw()
    saved = NR.api
    try:
        def unlock(table, pw="delegated"):
            NR.api = answering(table)
            w = NR.RemoteAdminWindow(root, "http://127.0.0.1:1")
            w.pw_e.insert(0, pw)
            w._unlock()
            root.update_idletasks()
            return w

        w = unlock({"/admin/server_config": OPEN_CFG,
                    "/transactions/delete": OPEN_POST,
                    "/records/import": OPEN_POST,
                    "/members/rename": OPEN_NAME,
                    "/assets/proposals/decide": OPEN_PROP,
                    "/assets/proposals": PROPOSALS,
                    "/admin/mail": OPEN_MAIL,
                    "/clients": OPEN_CLIENTS,
                    "/permissions": PERMS,
                    "/members": MEMBERS})
        eq("a password that opens all seven shows all seven", w.opens,
           ("config", "history", "import", "users", "mail", "proposals",
            "clients"))
        eq("and the Host and Port panel is filled from the read it already "
           "needed", w.host_e.get(), "0.0.0.0")
        eq("and the Mail panel is filled from its knock, which is the same "
           "read (#172)", w.mail.host_e.get(), "relay.example")
        eq("and the Engineers panel drew a card per Engineer the server "
           "listed", len(w.users.rows), 2)
        eq("and the Asset Proposals panel drew what is waiting, which is a "
           "read of its own rather than the knock - that one is refused on "
           "purpose", len(w.proposals.rows), 1)
        eq("and the Connected Clients panel drew the registry out of its own "
           "knock, which is the load (#174)", len(w.clients.rows), 1)
        eq("with the Permission captions served rather than carried here "
           "(rule 8)", [p["label"] for p in w.users.perms],
           ["Sees every Engineer's history"])
        w.win.destroy()

        w = unlock({"/admin/server_config": SHUT_CFG,
                    "/transactions/delete": OPEN_POST,
                    "/records/import": OPEN_POST,
                    "/members/rename": SHUT_POST,
                    "/assets/proposals/decide": SHUT_PROP,
                    "/admin/mail": SHUT_MAIL,
                    "/clients": SHUT_CLIENTS})
        eq("a Manage Transaction History password shows that alone", w.opens,
           ("history", "import"))
        w.win.destroy()

        # #171's own leg, widened by #172, #173 and #174: one capability -
        # `server_settings` - opens **all four** of its areas and none of the
        # three beside them. All four, because the decision those tickets made
        # is that each is that capability rather than a fifth one, and #174 is
        # the last of them: the capability is complete here, so a panel added
        # after it is a new capability rather than a fifth area of this one.
        w = unlock({"/admin/server_config": SHUT_CFG,
                    "/transactions/delete": SHUT_POST,
                    "/records/import": SHUT_POST,
                    "/members/rename": OPEN_NAME,
                    "/assets/proposals/decide": OPEN_PROP,
                    "/assets/proposals": PROPOSALS,
                    "/admin/mail": OPEN_MAIL,
                    "/clients": OPEN_CLIENTS,
                    "/permissions": PERMS,
                    "/members": MEMBERS})
        eq("a Server Settings password shows the Engineers, Mail, Asset "
           "Proposals and Connected Clients panels and nothing else", w.opens,
           ("users", "mail", "proposals", "clients"))
        w.win.destroy()

        # And the knock itself, driven rather than read: what it must not do is
        # write, and `POST /members` with a name would add an Engineer on every
        # unlock of this window.
        knocked = []

        def _knock(method, url, **kw):
            knocked.append(url)
            return _Answer(401, {"error": "Wrong password.",
                                 "code": "bad_password"})

        NR.api = _knock
        NR.probe_remote_admin("http://127.0.0.1:1", "delegated")
        paths = [u.split("127.0.0.1:1")[-1] for u in knocked]
        eq("nothing in the probe knocks on the door that adds an Engineer",
           [p for p in paths if p == "/members"], [])
        eq("nor on the one that records a proposal - a knock on "
           "`POST /assets/propose` would file one on every unlock (#173)",
           [p for p in paths if p == "/assets/propose"], [])
        if "/assets/proposals/decide" in paths:
            ok("the Asset Proposals door is knocked on with a decision "
               "carrying no id, which authorises first and writes nothing")
        else:
            bad("the probe no longer knocks on /assets/proposals/decide: %r"
                % (paths,))
        eq("and never on the read beside it, which needs no credential and "
           "would answer for any password",
           [p for p in paths if p.startswith("/assets/proposals?")], [])
        eq("nor on either of the two doors that command a Client - the "
           "registry read is the knock, and a knock that commands a machine "
           "is not one (#174)",
           [p for p in paths
            if p in ("/clients/command", "/clients/push_cert")], [])
        if "/clients" in paths:
            ok("the Connected Clients door is knocked on with the registry "
               "read itself, which is never open and is the panel's own load")
        else:
            bad("the probe no longer knocks on /clients: %r" % (paths,))
        if "/members/rename" in paths:
            ok("the Engineers door is knocked on with a rename carrying no id")
        else:
            bad("the probe no longer knocks on /members/rename: %r" % (paths,))

        # Import Transaction Archive is its own capability, so it is its own
        # panel - a password that opens the history must not carry it.
        w = unlock({"/admin/server_config": SHUT_CFG,
                    "/transactions/delete": SHUT_POST,
                    "/records/import": OPEN_POST,
                    "/members/rename": SHUT_POST,
                    "/assets/proposals/decide": SHUT_PROP,
                    "/admin/mail": SHUT_MAIL,
                    "/clients": SHUT_CLIENTS})
        eq("and an Import Archive password shows that alone", w.opens,
           ("import",))
        w.win.destroy()

        w = unlock({"/admin/server_config": SHUT_CFG,
                    "/transactions/delete": SHUT_POST,
                    "/records/import": SHUT_POST,
                    "/members/rename": SHUT_POST,
                    "/assets/proposals/decide": SHUT_PROP,
                    "/admin/mail": SHUT_MAIL,
                    "/clients": SHUT_CLIENTS})
        eq("a password that opens nothing opens no panel", w.opens, ())
        if "Wrong password" in w.err.cget("text"):
            ok("and is refused as a password, in the server's own words, "
               "rather than by opening an empty window")
        else:
            bad("a password that opens nothing left the window saying %r - an "
                "empty Remote Admin window reads as a server with nothing in "
                "it rather than a credential that reaches none of it"
                % w.err.cget("text"))
        if w.pw_e.winfo_exists():
            ok("and the password form is still there to try another one")
        else:
            bad("the password form is gone, so a refused password leaves "
                "nothing to type into")
        w.win.destroy()

        w = unlock({"/admin/server_config": INSECURE,
                    "/transactions/delete": INSECURE,
                    "/records/import": INSECURE,
                    "/members/rename": INSECURE,
                    "/assets/proposals/decide": INSECURE,
                    "/admin/mail": INSECURE,
                    "/clients": INSECURE})
        eq("plain http opens nothing either", w.opens, ())
        if "HTTPS" in w.err.cget("text"):
            ok("and says so in the server's own words, which is a different "
               "answer from a wrong password (R1: refused before the password "
               "is examined)")
        else:
            bad("an insecure refusal was shown as %r, so a delegate over "
                "plain http is told their password is wrong" %
                w.err.cget("text"))
        w.win.destroy()
    finally:
        NR.api = saved
        quiesce(root)


def check_the_notifier_remote_admin_answers_a_proposal():
    """The Asset Proposals panel. #173.

    What the console's Asset Proposals window does, from the machine an Admin
    happens to be at - and the three things about it that no static read and
    no live server can show, since what is being asserted is what this window
    *sends* for a given answer.

      - **A delivery is one card.** A batch has no column of its own (029): a
        delivery is every row carrying the one `proposed_at` it was stamped
        with, so the grouping is derived here exactly as it is derived at the
        console, and two rows from one file are one card while a row from
        another is its own.
      - **A group action is one call per row.** The endpoint answers one id,
        and that is the shape this needs rather than a limitation of it: the
        race this has refuses the row whose identifier reached the register
        while the proposal waited, in `_save_asset`'s own words, and the rest
        of the delivery still has to land. So a refusal in the middle is
        driven, and what is asserted is that the rows behind it were still
        sent and that the server's sentence is what is shown.
      - **A rejection is not sent without a reason.** It is the whole of what
        the Storekeeper is told, the server refuses one without it, and asking
        afterwards would be a refusal the Admin has to read to find out they
        were asked a question. Backing out of that question sends nothing at
        all, which is the leg that would otherwise reject a delivery with an
        empty reason.

    The list is re-read after every decision, because a panel still showing a
    proposal that has been answered is one somebody answers twice.

    `_prompt` is replaced rather than driven: it builds its own Toplevel and
    `wait_window`s on it deliberately - no grab, so nothing here can stop a
    Transaction being confirmed - and a nested event loop in a gate is a gate
    that hangs.
    """
    head("the Notifier's Remote Admin answers a proposal")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})
            self.ok = 200 <= status < 300

        def json(self):
            return self._body

    def rows():
        # Two of one delivery - one proposer, one `proposed_at` - and one
        # proposed on its own the day before.
        return [{"id": 11, "asset_number": "D-1", "serial_number": "DS-1",
                 "asset_type": "Laptop", "asset_model": "T14",
                 "proposed_by": "Storekeeper User (Storekeeper)",
                 "proposed_at": "2026-02-03T09:00:00", "status": "pending"},
                {"id": 12, "asset_number": "D-2", "serial_number": "DS-2",
                 "asset_type": "Laptop", "asset_model": "T14",
                 "proposed_by": "Storekeeper User (Storekeeper)",
                 "proposed_at": "2026-02-03T09:00:00", "status": "pending"},
                {"id": 13, "asset_number": "", "serial_number": "LS-9",
                 "asset_type": "Screen", "asset_model": "",
                 "proposed_by": "Storekeeper User (Storekeeper)",
                 "proposed_at": "2026-02-02T14:30:00", "status": "pending"}]

    sent = []

    def answering(refuse=()):
        """`api` recording every call, refusing the proposal ids in `refuse`."""
        def _api(method, url, **kw):
            body = dict(kw.get("json") or {})
            sent.append((method, url.split("127.0.0.1:1")[-1], body))
            if "/assets/proposals/decide" in url:
                if body.get("id") in refuse:
                    return _Answer(409, {
                        "error": "DS-2 is already the Serial Number of "
                                 "another asset.",
                        "code": "duplicate_identifier"})
                return _Answer(200, {"status": "ok",
                                     "proposal_id": body.get("id"),
                                     "proposal_status": "approved"})
            if "/assets/proposals" in url:
                return _Answer(200, rows())
            return _Answer(401, {"error": "Wrong password.",
                                 "code": "bad_password"})
        return _api

    root = tk.Tk()
    root.withdraw()
    root.geometry("320x140+0+0")
    saved = NR.api
    try:
        def panel(refuse=(), answer=None):
            del sent[:]
            NR.api = answering(refuse)
            w = NR.RemoteAdminWindow(root, "http://127.0.0.1:1",
                                     opens=("proposals",))
            # What the unlock would have left behind: `_call` sends it on
            # every action, there being no session here to hold open.
            w.password = "delegated"
            w._prompt = lambda title, text, field: answer
            root.update_idletasks()
            return w

        w = panel(answer="Already in the store.")
        eq("the panel is drawn from the pending list, which is a read of its "
           "own", len(w.proposals.rows), 3)
        eq("and the rows are grouped as they arrived - one delivery, one "
           "asset proposed on its own", [len(g) for g in
                                         w.proposals._deliveries()], [2, 1])

        # -- one row -------------------------------------------------------
        del sent[:]
        w.proposals._decide([w.proposals.rows[2]], True)
        posts = [(p, b) for m, p, b in sent if p == "/assets/proposals/decide"]
        eq("approving one proposal is one call naming it",
           [(b.get("id"), b.get("decision")) for p, b in posts],
           [(13, "approve")])
        eq("carrying the caller's own credential as `password`",
           posts[-1][1].get("password"), "delegated")
        if any(p.startswith("/assets/proposals?") for m, p, b in sent):
            ok("and the list is re-read afterwards, so an answered proposal "
               "is not left on screen to be answered again")
        else:
            bad("nothing re-read the list after a decision: %r"
                % ([p for m, p, b in sent],))
        w.win.destroy()

        # -- a delivery ----------------------------------------------------
        w = panel(answer=True)
        del sent[:]
        w.proposals._decide(w.proposals._deliveries()[0], True)
        posts = [b for m, p, b in sent if p == "/assets/proposals/decide"]
        eq("approving a delivery is one call per row, in the order the rows "
           "sit in", [b.get("id") for b in posts], [11, 12])
        w.win.destroy()

        # -- a refusal in the middle ---------------------------------------
        w = panel(refuse=(11,), answer=True)
        del sent[:]
        w.proposals._decide(w.proposals._deliveries()[0], True)
        posts = [b for m, p, b in sent if p == "/assets/proposals/decide"]
        eq("a row the register refuses does not refuse the delivery - the "
           "rest is still sent", [b.get("id") for b in posts], [11, 12])
        if "already the Serial Number" in w.err.cget("text") or \
                "approved" in w.err.cget("text"):
            ok("and the answer is the server's own sentence either way")
        else:
            bad("the refusal was reported as %r" % w.err.cget("text"))
        w.win.destroy()

        # -- a rejection needs a reason ------------------------------------
        w = panel(answer="")
        del sent[:]
        w.proposals._decide([w.proposals.rows[0]], False)
        eq("backing out of the reason sends nothing at all - an empty reason "
           "is refused by the server and tells the Storekeeper nothing",
           [p for m, p, b in sent if p == "/assets/proposals/decide"], [])
        w.win.destroy()

        w = panel(answer="Already in the store.")
        del sent[:]
        w.proposals._decide(w.proposals._deliveries()[0], False)
        posts = [b for m, p, b in sent if p == "/assets/proposals/decide"]
        eq("a rejection is asked for once for the delivery and carried on "
           "every row of it",
           [(b.get("id"), b.get("decision"), b.get("reason")) for b in posts],
           [(11, "reject", "Already in the store."),
            (12, "reject", "Already in the store.")])
        measure(tk, "Remote Admin, Asset Proposals panel", w.win)
        w.win.destroy()
    finally:
        NR.api = saved
        quiesce(root)


def check_the_notifier_remote_admin_manages_the_mail_settings():
    """The Mail panel and the Notification Rules window behind it. #172.

    Three things, none of them reachable from a static read: what the form
    sends, what it does with the one answer that comes back 200 and means
    failure, and which of the three password states it says.

      - **An empty password field means leave it.** The stored password is
        never sent back to this window (ADR-0013), so an empty field cannot be
        read as "clear it" - `smtp_password` is left out of the body
        altogether, which is how `POST /admin/mail` reads "keep", and Clear is
        a control of its own sending `""`. A form that sent an empty string on
        every save would wipe the relay's password the first time anybody
        corrected a typo in the host.
      - **A refused send is a 200.** The request did what it was asked and the
        failure is the relay's, so the answer carries `status: "failed"` and
        has to be read off the **body**; read off the status it reports a test
        that worked, which is worse than no test.
      - **A machine that cannot store one says so.** `can_store: false` is
        DPAPI being unavailable on that server, which needs a relay asking for
        no password rather than a better password - a different remedy, so a
        different sentence and a field that is not offered at all.

    The rules window is beside them because it is the same password and the
    same `_call`, and because what it must not lose is a recipient: the GET
    answers `to` as a **list** and the Entry holds a line, so the two have to
    meet without going through `str(list)`.

    Both windows are measured here rather than in the group above: they are
    only reachable behind an unlocked panel, and the panel needs a stubbed
    server to unlock against.
    """
    head("the Notifier's Remote Admin manages the mail settings")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})
            self.ok = 200 <= status < 300

        def json(self):
            return self._body

    MAIL = {"host": "relay.example", "port": 25, "from": "assets@example",
            "username": "svc", "starttls": True, "password_stored": True,
            "can_store": True}
    RULES = {"rules": [{"event": "update.failed",
                        "to": ["it@example", "sd@example"], "level": "error"}],
             "min_secs": 60, "hourly_max": 60}

    sent = []

    def answering(mail=None, test=None, rules=None):
        def _api(method, url, **kw):
            sent.append((method, url.split("127.0.0.1:1")[-1],
                         dict(kw.get("json") or {})))
            if "/admin/mail/test" in url:
                return test or _Answer(200, {"status": "ok"})
            if "/admin/mail" in url:
                return _Answer(200, dict(mail or MAIL)) if method == "get" \
                    else _Answer(200, {"status": "ok",
                                       "password_stored": True})
            if "/admin/notify_rules" in url:
                return _Answer(200, dict(rules or RULES)) if method == "get" \
                    else _Answer(200, {"status": "ok", "rules": 1})
            return _Answer(401, {"error": "Wrong password.",
                                 "code": "bad_password"})
        return _api

    root = tk.Tk()
    root.withdraw()
    root.geometry("320x140+0+0")
    saved = NR.api
    try:
        def panel(mail=None, test=None, rules=None):
            del sent[:]
            NR.api = answering(mail, test, rules)
            w = NR.RemoteAdminWindow(root, "http://127.0.0.1:1",
                                     opens=("mail",),
                                     config={"mail": dict(mail or MAIL)})
            # What the unlock would have left behind: `_call` sends it on
            # every action, there being no session here to hold open.
            w.password = "delegated"
            root.update_idletasks()
            return w

        w = panel()
        eq("the form is drawn from what the knock already answered",
           (w.mail.host_e.get(), w.mail.from_e.get(), w.mail.user_e.get(),
            w.mail.tls.get()),
           ("relay.example", "assets@example", "svc", 1))
        if "stored" in w.mail.pw_note.cget("text"):
            ok("and says a password is stored rather than showing one - the "
               "one replayable secret this server holds is never answered "
               "with (ADR-0013)")
        else:
            bad("the password note read %r" % w.mail.pw_note.cget("text"))

        del sent[:]
        w.mail._save()
        body = [b for m, p, b in sent if p == "/admin/mail"][-1]
        if "smtp_password" not in body:
            ok("an empty password field sends no smtp_password at all, which "
               "is how the endpoint reads 'keep what is stored'")
        else:
            bad("a save with an empty field sent smtp_password=%r, which "
               "clears the stored password on every ordinary save"
               % (body.get("smtp_password"),))
        eq("and the key is smtp_password rather than password, which is the "
           "caller's own credential at every door in that file",
           body.get("password"), "delegated")

        del sent[:]
        w.mail.pw_e.insert(0, "relaysecret")
        w.mail._save()
        body = [b for m, p, b in sent if p == "/admin/mail"][-1]
        eq("a typed password is sent as smtp_password",
           body.get("smtp_password"), "relaysecret")
        eq("and the field is emptied behind it, so it is not re-sent by the "
           "next save", w.mail.pw_e.get(), "")

        del sent[:]
        w.mail._clear()
        body = [b for m, p, b in sent if p == "/admin/mail"][-1]
        eq("Clear Password sends the empty string, which is what clears it",
           body.get("smtp_password"), "")

        # The test saves first, for the console's reason: a test that passes
        # against this form and fails against what is on the server is worse
        # than no test.
        del sent[:]
        w.mail.test_e.insert(0, "admin@example")
        w.mail._test()
        paths = [p for m, p, b in sent]
        eq("Send Test Mail saves before it sends",
           paths, ["/admin/mail", "/admin/mail/test"])
        w.win.destroy()

        # A refused send is 200 with the relay's own words in the body.
        w = panel(test=_Answer(200, {"status": "failed",
                                     "error": "relay.example:25 rejected the "
                                              "sender."}))
        w.mail.test_e.insert(0, "admin@example")
        w.mail._test()
        if "rejected the sender" in w.err.cget("text"):
            ok("a refused send is read off the body rather than the status, "
               "and reported in the relay's own words")
        else:
            bad("a refused send was reported as %r, so a test that failed "
                "reads as one that worked" % w.err.cget("text"))
        w.win.destroy()

        # DPAPI unavailable: a field that is not offered, and its own sentence.
        w = panel(mail=dict(MAIL, can_store=False, password_stored=False))
        eq("a server that cannot store a password does not offer the field",
           str(w.mail.pw_e.cget("state")), "disabled")
        if "DPAPI" in w.mail.pw_note.cget("text"):
            ok("and says why, rather than reporting a refusal later - there "
               "is deliberately no plaintext fallback (ADR-0013)")
        else:
            bad("the note read %r, which does not say what is wrong with that "
                "machine" % w.mail.pw_note.cget("text"))
        del sent[:]
        w.mail._save()
        body = [b for m, p, b in sent if p == "/admin/mail"][-1]
        if "smtp_password" not in body:
            ok("and saving the rest of the form sends no password either")
        else:
            bad("a save on a DPAPI-less server sent smtp_password=%r"
                % (body.get("smtp_password"),))
        measure(tk, "Remote Admin, Mail panel", w.win)

        # -- Notification Rules ------------------------------------------
        rw = NR.RemoteNotifyRulesWindow(w.mail.panel)
        root.update_idletasks()
        eq("the rules window drew a row per rule the server answered with",
           len(rw.rows), 1)
        eq("and the recipients arrived as a list and are shown as a line, "
           "rather than as the repr of one", rw.rows[0][2].get(),
           "it@example, sd@example")
        if "60" in rw.note.cget("text"):
            ok("and the two bounds are stated on the window, from the GET "
               "rather than from a copy kept here")
        else:
            bad("the rules window states no bounds: %r" % rw.note.cget("text"))
        del sent[:]
        rw._save()
        body = [b for m, p, b in sent if p == "/admin/notify_rules"][-1]
        eq("Save Rules sends the whole list, which is what the endpoint takes",
           body.get("rules"),
           [{"event": "update.failed", "to": "it@example, sd@example",
             "level": "error"}])
        measure(tk, "Remote Admin, Notification Rules", rw.win)
        survives_a_short_screen(tk, "Remote Admin, Notification Rules", rw.win)

        # A card per rule has no bound at all, so the window is driven past
        # what any screen holds through its own Add a rule - which is what
        # re-asks the region beside `fit` - rather than restubbed: what is
        # asserted is that the twenty-fifth rule lengthens the scroll and not
        # the window, and that Save Rules, Add a rule and Close are still
        # there at the end of it (#199).
        for _ in range(24):
            rw._add()
        root.update_idletasks()
        root.update()
        at = "Remote Admin, Notification Rules at 25 rules"
        measure(tk, at, rw.win)
        measure_scrolled_body(tk, at, rw.win)
        scroll_reaches_its_form(tk, at, rw.win)
        survives_a_short_screen(tk, at, rw.win)
        rw.win.destroy()
        w.win.destroy()
    finally:
        NR.api = saved
        quiesce(root)


def check_the_notifier_remote_admin_commands_a_client():
    """The Connected Clients panel. #174.

    The Server GUI's Connected Clients window from the machine an Admin
    happens to be standing at: the list, the certificate each installation
    says it pins, the commands queued against the selected one, and the three
    controls. None of it is reachable from a static read, and the three things
    worth driving are the three the console got wrong first.

      - **What a command body carries, and what it does not.** The row is
        named by `client_id` and the command by name, and **nothing names the
        issuer**: this is a credential rather than a person, so `issued_by` is
        `_remote_actor`'s sentence on the server and a name sent from here
        would be a delegated act filed under somebody's name. Push Certificate
        is a **route of its own** and sends no `client_id` at all, so
        commanding one machine and commanding every machine cannot be confused
        by a field left out.
      - **Push takes no selection and a per-Client command does.** The first
        is the whole fleet learning to accept a certificate before the binding
        moves (C3, ADR-0020), and doing that one machine at a time is how one
        gets missed; the second reaches into a machine somebody may be working
        at, so with nothing selected it has to refuse rather than pick a row.
      - **The certificate cell is a verdict against what this server serves**,
        read off the `served` fingerprint the same answer carries rather than
        worked out here - a panel deciding for itself which certificate is
        live would be answering the question with itself. A Client reporting
        none is a dash, since nothing pinned is nothing to strand, and where
        this server serves none there is no verdict at all.

    `api` is stubbed per path and `_prompt` is replaced, for the reason the
    Asset Proposals group gives: it builds its own Toplevel and waits on it,
    so a driven click would block on a window nothing is going to answer.
    What is asserted about the questions is that they were asked at all - a
    command that goes without one is a machine logged off by a stray click.
    """
    head("the Notifier's Remote Admin commands a Client")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body=None):
            self.status_code, self._body = status, (body or {})
            self.ok = 200 <= status < 300

        def json(self):
            return self._body

    SERVED = ("AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:"
              "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:9A")
    OTHER = SERVED[:-2] + "FE"
    REG = {"clients": [
        {"client_id": "c-1", "hostname": "HOST-L14", "app": "Notifier",
         "version": "2.3.0", "member": "Brian Dawson", "os_user": "bdawson",
         "address": "192.0.2.12", "cert_fingerprint": SERVED,
         "reported_address": "198.51.100.11",
         "first_seen": "2026-01-02T08:00:00",
         "last_seen": "2026-02-03T09:00:00", "age_secs": 30,
         "commands": [{"id": 4, "command": "trust_cert",
                       "issued_at": "2026-02-03T08:00:00",
                       "issued_by": 'Delegate: Server Settings held by '
                                    '"Brian Dawson" (remote)',
                       "expires_at": "2026-02-10T08:00:00",
                       "state": "queued"}]},
        {"client_id": "c-2", "hostname": "HOST-STORE", "app": "Storekeeper",
         "version": "2.3.0", "member": "", "os_user": "storeuser",
         "address": "192.0.2.20", "cert_fingerprint": OTHER,
         "first_seen": "2026-01-02T08:00:00",
         "last_seen": "2026-01-30T09:00:00", "age_secs": 400000,
         "commands": []},
        {"client_id": "c-3", "hostname": "HOST-NEW", "app": "Notifier",
         "version": "2.3.0", "member": "Carol Evans", "os_user": "cevans",
         "address": "192.0.2.31", "cert_fingerprint": "",
         "first_seen": "2026-02-01T08:00:00",
         "last_seen": "2026-02-03T08:50:00", "age_secs": 4000,
         "commands": []}],
        "served": SERVED, "staged": OTHER}

    sent = []

    def answering(refuse=None):
        """`api` recording every call, refusing the paths in `refuse`."""
        def _api(method, url, **kw):
            path = url.split("127.0.0.1:1")[-1]
            sent.append((method, path, dict(kw.get("json") or {})))
            if refuse and path in refuse:
                return refuse[path]
            if path in ("/clients/command", "/clients/push_cert"):
                return _Answer(200, {"status": "queued"})
            if path == "/clients":
                return _Answer(200, REG)
            return _Answer(401, {"error": "Wrong password.",
                                 "code": "bad_password"})
        return _api

    root = tk.Tk()
    root.withdraw()
    root.geometry("320x140+0+0")
    saved = NR.api
    try:
        def panel(asked=None):
            del sent[:]
            NR.api = answering()
            w = NR.RemoteAdminWindow(root, "http://127.0.0.1:1",
                                     opens=("clients",),
                                     config={"clients": REG})
            # What the unlock would have left behind: `_call` sends it on
            # every action, there being no session here to hold open.
            w.password = "delegated"

            def _prompt(title, text, field):
                (asked if asked is not None else []).append(title)
                return True
            w._prompt = _prompt
            root.update_idletasks()
            return w

        asked = []
        w = panel(asked=asked)
        eq("the list is drawn from what the knock already answered, rather "
           "than read a second time",
           (len(w.clients.rows), [p for m, p, b in sent]), (3, []))
        eq("and it is the console's own columns, with the identifiers of the "
           "machine first", [c for c, _w in w.clients.COLS][:3],
           ["Hostname", "App", "Version"])
        heads = [c for c, _w in w.clients.COLS]
        at = heads.index("Reported Address") if "Reported Address" in heads \
            else -1
        eq("Reported Address sits directly after Address (#281)",
           heads[at - 1] if at > 0 else None, "Address")
        eq("  painted with the claim, and a dash for a Client that sent none",
           (w.clients.tree.set("c-1", "Reported Address"),
            w.clients.tree.set("c-2", "Reported Address")),
           ("198.51.100.11", "\u2014"))
        eq("  with Address still the peer the server saw",
           w.clients.tree.set("c-1", "Address"), "192.0.2.12")

        # The certificate cell: a verdict against what this server serves.
        eq("an installation holding what is served reads OK",
           w.clients._cert_cell(SERVED)[:2], "OK")
        eq("one holding something else reads NO, which is who would be "
           "stranded if the certificate were replaced today",
           w.clients._cert_cell(OTHER)[:2], "NO")
        eq("and one that has reported none is a dash - nothing pinned is "
           "nothing to strand", w.clients._cert_cell(""), "\u2014")
        w.clients.served = ""
        eq("where this server serves no certificate there is no verdict at "
           "all, only the pairs", w.clients._cert_cell(OTHER),
           ".." + OTHER[-5:])
        w.clients.served = SERVED
        if "1 of 3" in w.clients.count.cget("text"):
            ok("the count says how many hold what is being served, off the "
               "server's own fingerprint rather than one worked out here")
        else:
            bad("the count line read %r" % w.clients.count.cget("text"))
        if "staged" in w.clients.count.cget("text"):
            ok("and says whether anything is staged, which is what decides "
               "whether a push has anything to push")
        else:
            bad("the count line says nothing about the staged certificate")

        # The selection: the whole fingerprint, and that row's own commands.
        w.clients.tree.selection_set("c-1")
        root.update()
        eq("the selected row's whole fingerprint is shown, which is where "
           "one is actually compared against another",
           w.clients.certline.cget("text"), SERVED)
        eq("and the commands under the list are that row's own",
           len(w.clients.cmds.get_children()), 1)
        w.clients.tree.selection_set("c-2")
        root.update()
        eq("selecting a Client with nothing queued empties the command list "
           "rather than leaving the last row's",
           len(w.clients.cmds.get_children()), 0)

        # A command: one call naming the row and the command, and no name.
        del sent[:]
        del asked[:]
        w.clients.tree.selection_set("c-1")
        root.update()
        w.clients._command("logoff")
        posts = [b for m, p, b in sent if p == "/clients/command"]
        eq("one command is one call naming the Client and the command",
           [(b.get("client_id"), b.get("command")) for b in posts],
           [("c-1", "logoff")])
        eq("and nothing in the body names the issuer - this is a credential "
           "rather than a person, so the row and the log entry carry "
           "_remote_actor's sentence",
           [k for k in posts[0] if "by" in k or "actor" in k], [])
        eq("  with the caller's own credential on it, as at every door",
           posts[0].get("password"), "delegated")
        eq("and it was asked about first", len(asked), 1)
        if any(p == "/clients" for m, p, b in sent):
            ok("and the registry is re-read afterwards, so the command "
               "appears as queued without waiting for anything")
        else:
            bad("a queued command left the list as it was: %r"
                % ([p for m, p, b in sent],))

        # With nothing selected: a refusal rather than a row picked for them.
        w.clients.tree.selection_remove(*w.clients.tree.selection())
        root.update()
        del sent[:]
        w.clients._command("reset_identity")
        eq("a per-Client command with nothing selected sends nothing - this "
           "reaches into a machine somebody may be working at",
           [p for m, p, b in sent if p == "/clients/command"], [])
        if "Select" in w.err.cget("text"):
            ok("and says to select one, rather than picking a row")
        else:
            bad("nothing selected was reported as %r" % w.err.cget("text"))

        # Push: no selection, no client_id, its own route.
        del sent[:]
        del asked[:]
        w.clients._push()
        posts = [b for m, p, b in sent if p == "/clients/push_cert"]
        eq("Push Certificate needs no selection and is one call",
           len(posts), 1)
        eq("and sends no client_id at all - commanding one machine and "
           "commanding every machine are different acts, and the second must "
           "not be reachable by leaving a field out of the first",
           "client_id" in posts[0], False)
        eq("  and it was asked about first", len(asked), 1)
        eq("and it never goes through the per-Client route",
           [p for m, p, b in sent if p == "/clients/command"], [])
        # A refusal is the server's own sentence: a Client that has never
        # checked in, a command already waiting and a staged certificate that
        # is not there are three different things to do something about. The
        # same window throughout, the stub being swapped rather than the
        # panel rebuilt - a second Remote Admin window would be a second
        # theme registration over a destroyed one, which Tk reports on
        # stderr and no assertion here is about.
        for path, answer, words in (
                ("/clients/command",
                 _Answer(409, {"error": "A logoff is already queued for "
                                        "HOST-L14.",
                               "code": "already_queued"}),
                 "already queued"),
                ("/clients/push_cert",
                 _Answer(409, {"error": "No certificate is staged.",
                               "code": "no_staged_cert"}),
                 "staged")):
            NR.api = answering({path: answer})
            w.clients.tree.selection_set("c-1")
            root.update()
            if path == "/clients/command":
                w.clients._command("logoff")
            else:
                w.clients._push()
            if words in w.err.cget("text"):
                ok("%s refused is shown in the server's own words" % path)
            else:
                bad("%s refused was shown as %r, so three different refusals "
                    "read the same" % (path, w.err.cget("text")))

        measure(tk, "Remote Admin, Connected Clients panel", w.win)
        w.win.destroy()
        root.update()
    finally:
        NR.api = saved
        quiesce(root)
