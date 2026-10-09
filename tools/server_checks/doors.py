r"""Every route declares the credential it wants (#209).

One of the check groups #221 split tools/server-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged server, the sources, ok()/bad()/eq() - comes from
server_checks.stage, which builds the one staging tree at import.
"""
import ast

from server_checks.stage import (M, SRC, bad, head, ok, stage_import)



# ── every route declares the credential it wants (#209) ──────────────────────

# The three names a route's body may reach a credential through, plus the two
# named doors that wrap one of them. A route declaring DOOR_OPEN may call none
# of these, which is the assertion that stops "open" being written over a route
# that is in fact guarded - and stops a guarded route being quietly opened by
# deleting a line, since the declaration would then contradict the body.
_CRED_CALLS = ("_admin_password_ok", "password_matches", "_remote_admit",
               "_remote_authorise", "_member_door", "_mail_door")
# Helpers that ask one capability on a route's behalf. Their own capability is
# read out of them rather than written down here, so a door that is re-pointed
# at another capability moves every route behind it in this check too.
_DOOR_HELPERS = ("_member_door", "_mail_door")


def _calls_in(node):
    """Every function name called anywhere inside `node`, as written."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.id if isinstance(f, ast.Name) else (
            f.attr if isinstance(f, ast.Attribute) else "")
        out.append((name, n))
    return out


def _capability_asked(node, helpers):
    """The capability literal a body asks for, or "" where it asks for none.

    Reads the first positional argument of `_remote_admit` /
    `_remote_authorise`, and resolves `_member_door` / `_mail_door` to whatever
    *they* ask - so the answer is what the route actually reaches rather than
    what its declaration claims.
    """
    for name, call in _calls_in(node):
        if name in ("_remote_admit", "_remote_authorise"):
            if call.args and isinstance(call.args[0], ast.Constant):
                return call.args[0].value
            return "?"
        if name in helpers:
            return helpers[name]
    return ""


def check_every_route_declares_the_credential_it_wants():
    """No route is guarded only because its author remembered. #209.

    `server.py` carries a `door(...)` line under every `@app.route`, and this
    is what makes it load-bearing rather than a comment: a route with no
    declaration fails here, and a declaration that does not match what the body
    reaches fails here too. Before this, an absent line was how an intentionally
    open route (ADR-0002) and a forgotten one both read.

    The negative half is the route count and the five declaration kinds: a run
    that enumerated nothing, or that found no capability route left to check,
    would otherwise report a clean sweep for ever.
    """
    head("every route declares the credential it wants")
    tree = ast.parse(SRC)
    routes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        is_route = any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and d.func.attr == "route" for d in node.decorator_list)
        if is_route:
            routes[node.name] = node
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef)}

    # ── the enumeration is real ──
    print("        %d route(s) in server.py, %d declaration(s) registered"
          % (len(routes), len(M.ROUTE_DOORS)))
    if len(routes) >= 40:
        ok("%d routes enumerated" % len(routes))
    else:
        bad("only %d routes enumerated - this file has ~48, so the parse "
            "found nothing and every assertion below is vacuous"
            % len(routes))
        return

    # ── every route carries a declaration ──
    undeclared = sorted(n for n in routes if n not in M.ROUTE_DOORS)
    if undeclared:
        for n in undeclared:
            bad("%s is a route and declares no credential - add a door(...) "
                "line, DOOR_OPEN with a `why` if it is open on purpose" % n)
    else:
        ok("all %d routes declare a credential" % len(routes))
    orphan = sorted(n for n in M.ROUTE_DOORS if n not in routes)
    if orphan:
        for n in orphan:
            bad("%s declares a door and is not a route" % n)
    else:
        ok("every declaration belongs to a route")

    # ── the three fixed credentials cannot be read as capability names ──
    fixed = (M.DOOR_OPEN, M.DOOR_ADMIN, M.DOOR_OWN)
    clash = sorted(set(fixed) & set(M.CAPABILITIES))
    if clash:
        bad("%s is both a fixed credential and a capability name - a "
            "declaration naming it means two things" % ", ".join(clash))
    else:
        ok("open / admin / own name no capability")

    # ── ssl_cert never reaches an endpoint (rule 1, ADR-0015) ──
    creds = {n: M.ROUTE_DOORS[n][0] for n in routes if n in M.ROUTE_DOORS}
    off = sorted(n for n, c in creds.items()
                 if c not in fixed and c not in M.CAPABILITY_REMOTE)
    if off:
        for n in off:
            bad("%s declares %s, which is not in CAPABILITY_REMOTE - "
                "ssl_cert above all must never reach an endpoint (rule 1)"
                % (n, creds[n]))
    else:
        ok("no route declares a capability outside CAPABILITY_REMOTE")

    # ── the declaration against the body ──
    helpers = {h: _capability_asked(fns[h], {}) for h in _DOOR_HELPERS
               if h in fns}
    missing_helper = [h for h in _DOOR_HELPERS if h not in fns]
    if missing_helper:
        bad("%s is gone - the capability behind the routes it fronted cannot "
            "be resolved" % ", ".join(missing_helper))
        return
    print("        door helpers: %s"
          % ", ".join("%s -> %s" % (h, c) for h, c in sorted(helpers.items())))

    seen = {"open": 0, "admin": 0, "own": 0, "capability": 0, "optional": 0}
    mismatched = []
    for name in sorted(routes):
        if name not in M.ROUTE_DOORS:
            continue
        cred, why, optional = M.ROUTE_DOORS[name]
        body = routes[name]
        called = {c for c, _ in _calls_in(body)}
        if optional:
            seen["optional"] += 1
        if cred == M.DOOR_OPEN:
            seen["open"] += 1
            reached = sorted(called & set(_CRED_CALLS))
            if reached:
                mismatched.append(
                    "%s declares open and its body reaches %s"
                    % (name, ", ".join(reached)))
        elif cred == M.DOOR_ADMIN:
            seen["admin"] += 1
            if "_admin_password_ok" not in called:
                mismatched.append(
                    "%s declares admin and never asks _admin_password_ok"
                    % name)
            if called & {"_remote_admit", "_remote_authorise"}:
                mismatched.append(
                    "%s declares admin and reaches the capability channel - "
                    "a capability password would open it" % name)
        elif cred == M.DOOR_OWN:
            seen["own"] += 1
            if "password_matches" not in called:
                mismatched.append(
                    "%s declares own and never checks an Engineer's stored "
                    "hash" % name)
        else:
            seen["capability"] += 1
            asked = _capability_asked(body, helpers)
            if asked != cred:
                mismatched.append(
                    "%s declares %s and its body asks for %s"
                    % (name, cred, asked or "no capability at all"))
            if "_admin_password_ok" in called:
                mismatched.append(
                    "%s declares %s and checks the admin password itself - "
                    "that is the transport rule bypassed" % (name, cred))
    if mismatched:
        for m in mismatched:
            bad(m)
    else:
        ok("every declaration matches what its route's body reaches")

    # ── an open route says why, and the negative half of the sweep ──
    silent = sorted(n for n in routes
                    if M.ROUTE_DOORS.get(n, ("", "", False))[0] == M.DOOR_OPEN
                    and not M.ROUTE_DOORS[n][1])
    if silent:
        for n in silent:
            bad("%s is open and says nothing about why" % n)
    else:
        ok("every open route states why it is open")
    print("        open %(open)d  admin %(admin)d  own %(own)d  "
          "capability %(capability)d  "
          "(optional %(optional)d)" % seen)
    thin = sorted(k for k, v in seen.items() if not v)
    if thin:
        bad("no route of kind(s) %s was checked - the assertions above for "
            "%s passed by finding nothing" % (", ".join(thin),
                                              ", ".join(thin)))
    else:
        ok("all five declaration kinds were exercised")


# Three routes read the credential under another key, and five parse a field
# before they reach their door - so a probe sending a bare `password` never
# arrives and reads back a 400 that says nothing about the door. What each one
# needs is written here rather than the assertion being softened for them.
_PW_KEY = {"admin_change_password": "current_password",
           "auth_change_password": "current_password"}
_PROBE_BODY = {"admin_change_password": {"new_password": "doors-admin-209"},
               "auth_change_password": {"name": "Brian Dawson",
                                        "new_password": "doors-own-209"},
               "cancel_transaction": {"id": 1},
               "add_member": {"name": "Brian Dawson"},
               "delete_member": {"name": "nobody at all"},
               "rename_member": {"id": 1, "name": "Brian Dawson"}}
_PROBE_PATH = {"<int:trans_id>": "1", "<path:member>": "Brian Dawson",
               "<key>": "notifier"}


def check_every_route_answers_as_its_door_declares():
    """The declaration against the running server, enumerated. #209.

    `check_every_route_declares_the_credential_it_wants` reads the source: that
    each route declares a credential and that its body reaches the matching
    check. This one asks the server. Every route is sent the request three ways
    - no credential, a wrong password, the right one - and the three answers are
    held against the declaration: a route declaring a capability refuses both of
    the first two with 401 and opens for the admin password and for **its own**
    capability password alone, an `admin` or `own` route refuses every capability
    password, and a route declaring `open` never answers 401 at all.

    That last one is the assertion worth having. A route declared open and in
    fact guarded is the defect this ticket is about, written the other way
    round, and no reading of the source catches it once the declaration and the
    body have been made to agree with each other and both are wrong.

    The transport rule is **not** what this asks. A capability password is
    HTTPS-only (ADR-0015) and the test client is not TLS, so `_remote_tls_ok` is
    forced here and the credential is what is left; the groups that own the
    transport rule are the ones that turn it off again.

    The negative half is the enumeration itself - the route count, and that at
    least one route of each declaration kind was probed.
    """
    head("every route answers as its door() declares")
    mod, _ = stage_import("doors", {})
    admin = "doors-admin-209"
    cappw = {c: "doors-cap-" + c for c in mod.CAPABILITY_REMOTE}
    mod._update_admin_cfg(password_hash=mod.hash_password(admin))
    have = {}
    for c, pw in cappw.items():
        have[c] = mod.hash_password(pw)
    mod._update_admin_cfg(capability_hashes=have)
    mod.init_db()
    # POST /auth/change_password refuses 409 no_password before it reaches its
    # door where the Engineer has none to change, so one is set - otherwise the
    # probe reports a refusal that is about the row rather than about the door.
    mod._save_member("Brian Dawson", None, None, member_password="doors-own-209",
                     authorised_as="Admin")
    _tls = mod._remote_tls_ok
    mod._remote_tls_ok = lambda: True
    try:
        _probe_every_door(mod, admin, cappw)
    finally:
        mod._remote_tls_ok = _tls


def _probe_every_door(mod, admin, cappw):
    """The body of the check above, so the TLS override is always put back."""
    rules = {}
    for r in mod.app.url_map.iter_rules():
        if r.endpoint != "static":
            rules.setdefault(r.endpoint, []).append(r)

    def call(rule, pw):
        body = dict(_PROBE_BODY.get(rule.endpoint, {}))
        if pw is not None:
            body[_PW_KEY.get(rule.endpoint, "password")] = pw
        path = rule.rule
        for token, val in _PROBE_PATH.items():
            path = path.replace(token, val)
        post = "POST" in rule.methods
        with mod.app.test_client() as c:
            fn = c.post if post else c.get
            return fn(path, json=body).status_code

    bad_rows = []
    seen = {"open": 0, "admin": 0, "own": 0, "capability": 0}
    probed = 0
    for view, (cred, _why, optional) in sorted(mod.ROUTE_DOORS.items()):
        for rule in rules.get(view, []):
            probed += 1
            tag = "%s %s" % ("POST" if "POST" in rule.methods else "GET",
                             rule.rule)
            none_, wrong, right = (call(rule, None),
                                   call(rule, "definitely-not-it"),
                                   call(rule, admin))
            if cred == mod.DOOR_OPEN:
                seen["open"] += 1
                if 401 in (none_, wrong, right):
                    bad_rows.append("%s declares open and answered 401 "
                                    "(%d/%d/%d)" % (tag, none_, wrong, right))
            else:
                if optional:
                    if none_ == 401:
                        bad_rows.append("%s declares %s and is marked open "
                                        "until a password is offered, and "
                                        "refused a body carrying none"
                                        % (tag, cred))
                elif none_ != 401:
                    bad_rows.append("%s declares %s and answered %d to a body "
                                    "with no credential" % (tag, cred, none_))
                if wrong != 401:
                    bad_rows.append("%s declares %s and answered %d to a wrong "
                                    "password" % (tag, cred, wrong))
                if right == 401:
                    bad_rows.append("%s declares %s and refused the admin "
                                    "password, which opens everything"
                                    % (tag, cred))
            if cred in mod.CAPABILITY_REMOTE:
                seen["capability"] += 1
                if call(rule, cappw[cred]) == 401:
                    bad_rows.append("%s declares %s and refused that "
                                    "capability's own password" % (tag, cred))
                for other in sorted(mod.CAPABILITY_REMOTE):
                    if other != cred and call(rule, cappw[other]) != 401:
                        bad_rows.append("%s declares %s and accepted the %s "
                                        "password" % (tag, cred, other))
            elif cred in (mod.DOOR_ADMIN, mod.DOOR_OWN):
                seen[cred] += 1
                for c, pw in sorted(cappw.items()):
                    if call(rule, pw) != 401:
                        bad_rows.append("%s declares %s and accepted the %s "
                                        "capability password" % (tag, cred, c))
    print("        %d route(s) probed three ways each" % probed)
    if probed < 40:
        bad("only %d route(s) probed - this server has ~48, so the url map "
            "answered with nothing and every assertion here is vacuous"
            % probed)
        return
    ok("%d routes probed" % probed)
    if bad_rows:
        for b in bad_rows:
            bad(b)
    else:
        ok("every route answered as its door() declares")
    print("        open %(open)d  admin %(admin)d  own %(own)d  "
          "capability %(capability)d" % seen)
    thin = sorted(k for k, v in seen.items() if not v)
    if thin:
        bad("no route of kind(s) %s was probed - the assertions for %s passed "
            "by finding nothing" % (", ".join(thin), ", ".join(thin)))
    else:
        ok("every declaration kind was probed")
