"""
Asset Manager - the Engineers register.

The six functions that read and write the `team_members` table: one Engineer
by name (`_member_row`), the same one by id after a rename has moved the name
(`_member_row_by_id`), the whole list (`_member_rows`), the one writer of a
row (`_save_member`), the removal (`_delete_member`) and the correction of a
name (`_rename_member`).

Lifted out of `server.py` by #217 unchanged - the Engineers third of the one
Register 039 (#210) named, and the last of the three to land. It was 039's own
first example: the routes here and the console reading one table through
different code. They are neither's. Nineteen calls in `server.py`'s own
routes, eleven in `server_gui.py`'s Manage Users as `S.<name>`, and ten
straight from `tools/server-checks.py` - two adapters and a gate already
reaching the cluster the same way before there was a module to name it.

**Independent of the other two registers.** An Engineer's name, password hash
and auto-approve flag carry no asset identity, so nothing here asks
`register_assets` which asset a row is about the way `register_transactions`
has to. What this table's rows are named in - `transactions.team_member` and
`clients.member` - are spellings this module rewrites when a name is
corrected, not keys another register owns.

Headless-safe: nothing here draws, so `server.py` imports it at module level.

**It opens no connection of its own.** `get_db` is `server.py`'s, and comes
over through `bind()` at import the way `register_assets.py` takes its two and
`server_cert.py` takes its paths - `from server import get_db` would execute
the whole server a second time rather than reach the one running, because
`server.py` runs as `__main__` under `applaunch`'s `runpy.run_path`. Every
other name below comes the same way and for the same reason.

**The password check did not move an inch.** `_save_member`, `_delete_member`
and `_rename_member` each check an admin password or an `authorised_as`
inline, exactly where they checked it in `server.py`; `_admin_password_ok` is
bound rather than folded in. 038 (#209) is the ticket that makes rule 7 one
enforcement point, and it has to find these three checks where it was filed
expecting them rather than somewhere this move put them.

`_KEEP` is the one name that came the other way. It is defined here rather
than bound, because `_save_member`'s signature *defaults* to it: a sentinel
assigned after import would leave those defaults holding the `None` the module
was loaded with while callers compared against the bound object, and every
unsent field would read as sent. So the one object lives beside the signature
that carries it and `server.py` imports it back flat, the way it imports
`_IDENTIFIER_TAKEN` back from `register_assets` - which is what keeps
`_save_mail_settings` and `POST /mail_settings`, its two readers over there,
comparing against the same object these three functions do.
"""

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there and
# here as one thing.
get_db = None
_log_event = None
_admin_password_ok = None
_member_permissions = None
_set_member_password = None
_storekeeper_actor = None
_storekeeper_can_add_engineer = None
_RENAMED_SEP = None
PASSWORD_MIN = None
PERMISSIONS = None


def bind(*, get_db, log_event, admin_password_ok, member_permissions,
         set_member_password, storekeeper_actor, storekeeper_can_add_engineer,
         renamed_sep, password_min, permissions):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `register_assets.bind()`,
    `register_transactions.bind()` and `server_cert.bind()` carry: every name
    the moved code reads out of `server.py` is on this list, so what the two
    modules share is one signature to read rather than a search of the file.

    Four of them are the enforcement points either side of an Engineer rather
    than the register itself - the admin password, the Storekeeper's switch and
    actor, and the one writer of an Own Password - and they stayed in
    `server.py` because they answer for more than this table. `_RENAMED_SEP`
    stayed for the plainer reason: `_parse_renamed` reads it back there.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports a
    second, and it gives each staged copy a `register_engineers` of its own.
    """
    # `global get_db` is a syntax error where `get_db` is also the parameter,
    # and the moved code calls it bare - so the module global is set the one
    # way left rather than the name being spelt differently on each side.
    globals()["get_db"] = get_db
    global _log_event, _admin_password_ok, _member_permissions
    global _set_member_password, _storekeeper_actor
    global _storekeeper_can_add_engineer, _RENAMED_SEP
    global PASSWORD_MIN, PERMISSIONS
    _log_event = log_event
    _admin_password_ok = admin_password_ok
    _member_permissions = member_permissions
    _set_member_password = set_member_password
    _storekeeper_actor = storekeeper_actor
    _storekeeper_can_add_engineer = storekeeper_can_add_engineer
    _RENAMED_SEP = renamed_sep
    PASSWORD_MIN = password_min
    PERMISSIONS = permissions


def _member_row(name):
    conn = get_db()
    row = conn.execute("SELECT * FROM team_members WHERE name=?", (name,)).fetchone()
    conn.close()
    return row


def _member_row_by_id(member_id):
    """One Engineer by id, or None. The lookup a rename does not break.

    A name moves and an id does not, so this is how a Client that has learnt
    one finds the Engineer again after their name has been corrected - and how
    `_rename_member` names the row it is about without having to say which
    spelling it currently has.
    """
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM team_members WHERE id=?",
                            (member_id,)).fetchone()
    finally:
        conn.close()


def _member_rows():
    """Every Engineer, for the Server GUI's Manage Users window.

    Reads the table rather than GET /members, for the reason `_client_rows`
    gives: this console is the process that owns the database, and going out
    over its own HTTP listener to read it would make the window depend on the
    listener being up.
    """
    conn = get_db()
    rows = conn.execute("SELECT * FROM team_members ORDER BY name").fetchall()
    conn.close()
    return rows


#: "this caller sent no such field" - keep whatever is stored. A sentinel
#: rather than None, because None is a value a caller can legitimately send.
_KEEP = object()


def _save_member(name, admin_password, auto_approve,
                 profile=_KEEP, permissions=_KEEP, member_password=_KEEP,
                 authorised_as=None):
    """Add or update one Engineer. The admin password, or a bare creation.

    The enforcement point POST /members and the Server GUI's Manage Users
    window share - the same shape _create_transaction and _cancel_transaction
    have, for the same reason: a rule that holds at the endpoint and quietly
    not in the window an Admin uses is exactly where somebody reaches for a way
    past it.

    `admin_password=None` means no password was offered at all, which is the
    Storekeeper's create-only path (ADR-0017) and is allowed while
    `storekeeper_can_add_engineer` is on. It is exactly `_cancel_transaction`'s
    convention and is the reason it is None rather than '': a body with no
    `password` key is the unauthenticated path, while `password: ""` is an
    attempt at the admin path and is refused as wrong. A wrong password never
    falls back to the delegated path - that would let a typo silently downgrade
    an Admin and produce a refusal naming the wrong reason.

    **Three things bound that path, and each is a different rule.** The switch
    says whether it is open at all. A name that already exists is refused
    `already_exists`, because an update is an edit and this delegates creation
    alone - without it, "create" would reach every field on an Engineer who is
    already on the list. And a `profile`, a `permissions` list or a
    `member_password` sent without a password is refused outright rather than
    ignored: an Engineer created this way starts on the Default profile with no
    credential of any kind, and silently dropping the field would let a caller
    believe it had been applied.

    `_KEEP` means the caller sent no such field, so what is stored survives: a
    client built before profiles existed can still toggle Auto-Approve without
    wiping one. `auto_approve` is deliberately not in that set - the endpoint
    has always read an absent one as false, and a caller on the wire must keep
    getting the answer it has always got.

    `_authorise` is deliberately not called from here, and `authorised_as` is
    why it does not have to be (#171): the endpoint has already proved the
    admin password or the **Server Settings** capability password through
    `_remote_authorise` and is naming who the entry belongs to. What that
    delegates is a second Admin rather than one action - whoever can add an
    Engineer or set their Own Password can then be that Engineer at that
    Engineer's client (ADR-0009) - which is exactly why it was not delegable
    before #171 and is the thing that ticket decided to hand over on purpose.
    It is **not** the Storekeeper's path: `admin_password is None` still means
    create-only, and the two are different arguments so a caller cannot reach
    one by leaving the other out.

    Returns (payload, http_status) like the other enforcement helpers here, so
    a caller renders a refusal it did not have to word itself.
    """
    delegated = admin_password is None and authorised_as is None
    if delegated:
        if not _storekeeper_can_add_engineer():
            return {"error": "Adding an engineer has been switched off on the "
                             "server. An admin adds one in the Server GUI's "
                             "Manage Users window.",
                    "code": "add_engineer_disabled"}, 403
        if profile is not _KEEP or permissions is not _KEEP \
                or member_password is not _KEEP:
            return {"error": "An engineer added without the admin password is "
                             "created on the Default profile with no own "
                             "password. The profile, the permissions and the "
                             "own password are set in the Server GUI's Manage "
                             "Users window.",
                    "code": "create_only"}, 403
    elif authorised_as is None and not _admin_password_ok(admin_password):
        return {"error": "Wrong admin password"}, 401
    name = (name or '').strip()
    if not name:
        return {"error": "Name required"}, 400
    auto = 1 if auto_approve else 0

    conn = get_db()
    existing = conn.execute("SELECT * FROM team_members WHERE name=?",
                            (name,)).fetchone()
    if delegated and existing:
        # An update is an edit, and the name is matched NOCASE, so this also
        # catches a second spelling of an Engineer who is already here. The
        # refusal names them in the spelling the register holds rather than the
        # one that was typed, which is the answer the caller wanted anyway -
        # that Engineer can be picked now.
        conn.close()
        return {"error": "%s is already on the engineer list. Changing an "
                         "engineer is the Server GUI's Manage Users window."
                         % existing["name"],
                "code": "already_exists"}, 409

    # Every field an older client does not send keeps its current value. INSERT
    # OR REPLACE used to be fine when auto_approve was the only column; now it
    # would wipe an engineer's profile and password whenever a client built
    # before this change toggled auto-approve.
    stored_profile = existing["profile"] if existing else "default"
    if profile is not _KEEP:
        stored_profile = "custom" if str(profile) == "custom" else "default"

    perms = existing["permissions"] if existing else ""
    if permissions is not _KEEP:
        asked = permissions or []
        if isinstance(asked, str):
            asked = [p.strip() for p in asked.split(",")]
        unknown = [p for p in asked if p not in PERMISSIONS]
        if unknown:
            conn.close()
            return {"error": "Unknown permission(s): " + ", ".join(unknown)}, 400
        perms = ",".join(p for p in PERMISSIONS if p in asked)

    # Checked before anything is written, so a password too short leaves no
    # half-applied change behind. _KEEP means the caller sent no member_password
    # at all, which is the convention above - keep what is there. '' means
    # clear it.
    new_pw = None
    if member_password is not _KEEP:
        new_pw = member_password or ''
        if new_pw and len(new_pw) < PASSWORD_MIN:
            # Checked here as well as in the helper below, and worded the same
            # as it words it: the row is written below, so refusing after that
            # would create the Engineer and refuse their password in one call.
            # A caller sees whichever check fires first, so the two say the
            # same thing and carry the same code.
            conn.close()
            return {"error": "An Own Password must be at least %d "
                             "characters." % PASSWORD_MIN,
                    "code": "too_short"}, 400

    # `name` is in the SET list because the conflict now fires on a name that
    # differs only in case: that is the same Engineer, so this is a correction
    # to their spelling rather than a second row - which is what it used to
    # produce. The Transactions already recorded keep the spelling they were
    # written with, that column being a label and not a key.
    #
    # password_hash and must_change_password are deliberately out of this
    # statement. They are written below, through the one helper the Server GUI
    # dialogs also go through, so arming the temporary flag cannot hold here
    # and quietly not at the console. Leaving them out of the ON CONFLICT SET
    # list is also what keeps an unsent password an untouched one, the same
    # convention the three fields above follow.
    conn.execute("""INSERT INTO team_members(name, auto_approve, profile, permissions)
                    VALUES (?,?,?,?)
                    ON CONFLICT(name) DO UPDATE SET
                        name          = excluded.name,
                        auto_approve  = excluded.auto_approve,
                        profile       = excluded.profile,
                        permissions   = excluded.permissions""",
                 (name, auto, stored_profile, perms))
    conn.commit()
    conn.close()

    if new_pw is not None:
        # The admin password is checked a second time, inside the helper. That
        # is a tenth of a second (ADR-0008) on an admin path used a few times a
        # month, and it buys one place that answers "what may set an Engineer's
        # Own Password" instead of two that have to agree.
        payload, status = _set_member_password(name, new_pw, admin_password,
                                              authorised_as=authorised_as)
        if status >= 400:
            return payload, status

    row = _member_row(name)
    # The row in team_members is the current state; this is the act that
    # changed it, which that table does not keep.
    _log_event("member.saved",
               "%s  auto_approve=%s  profile=%s" % (name, bool(auto),
                                                    stored_profile),
               actor=_storekeeper_actor() if delegated
               else (authorised_as or "Admin"))
    return {
        "status":       "ok",
        "id":           row["id"],
        "name":         name,
        "auto_approve": bool(auto),
        "profile":      stored_profile,
        "permissions":  _member_permissions(row),
        "has_password": bool(row["password_hash"]),
        "must_change_password": bool(row["must_change_password"]),
    }, 200


def _delete_member(name, admin_password, authorised_as=None):
    """Remove one Engineer from the Engineer list. The admin password, or #171's.

    History is untouched: team_member is stored as text on every Transaction,
    so the records an Engineer already has stay exactly as they were and only
    the list they are offered from shrinks.

    The enforcement point POST /members/delete and the Manage Users window
    share, for the reason _save_member gives. `authorised_as` is the Server
    Settings capability reaching it (#171), on that function's terms.
    """
    if authorised_as is None and not _admin_password_ok(admin_password):
        return {"error": "Wrong admin password"}, 401
    name = (name or '').strip()
    if not name:
        return {"error": "Name required"}, 400
    conn = get_db()
    cur = conn.execute("DELETE FROM team_members WHERE name=?", (name,))
    conn.commit()
    conn.close()
    _log_event("member.deleted", name, actor=authorised_as or "Admin",
               level="warn")
    return {"status": "ok", "deleted": cur.rowcount, "name": name}, 200


def _rename_member(member_id, new_name, admin_password, authorised_as=None):
    """Correct one Engineer's name. The admin password, or #171's.

    The one writer of a rename, the way `_save_member` is the one writer of a
    row and `_delete_member` the one remover. The Server GUI's Manage Users
    window is one caller and `POST /members/rename` is the other.

    **There was deliberately no endpoint until #171**, on the grounds that the
    Admin at this console is the only actor - the same call Add Transaction,
    Modify, the Client commands and the Lookup Sheet made. What changed is
    where the Admin is standing rather than the rule, which is the argument
    that put `POST /transactions/modify` on the network at R1: a delegate who
    can add an Engineer, delete one and set an Own Password, and who has to
    walk to the console to correct a misspelt name, leaves it misspelt. It is
    still not `_authorise`'s to answer - `authorised_as` is a credential the
    endpoint has already proved through `_remote_authorise`, on
    `_save_member`'s terms.

    **The register moves with the name.** `transactions.team_member` and
    `clients.member` hold a spelling rather than a key, but every one of those
    rows is about the same person, and an Engineer whose past movements are
    filed under a name they no longer have has had their history cut in half -
    which is what somebody reconstructing a dispute is looking for. Both are
    rewritten in the same transaction as the row itself, so there is no moment
    at which they disagree.

    **`system_log` is never rewritten.** It records what was done, by whom, at
    the time, and an audit trail edited to agree with a later decision is not
    one. The act is recorded instead - `member.renamed`, naming both spellings
    and the id they belong to, which is also what `_former_member_name` reads
    to answer a Notifier still polling under the old name.

    Returns (payload, http_status) like the other enforcement helpers here.
    """
    if authorised_as is None and not _admin_password_ok(admin_password):
        return {"error": "Wrong admin password"}, 401
    new_name = (new_name or '').strip()
    if not new_name:
        return {"error": "Name required", "code": "no_name"}, 400
    row = _member_row_by_id(member_id)
    if row is None:
        return {"error": "No such Engineer", "code": "no_member"}, 404
    old_name = str(row["name"])
    conn = get_db()
    # NOCASE, so a name differing from another Engineer's only in case is the
    # collision it would be at every other door here - and a correction to this
    # Engineer's own capitalisation is not one, which is why the id is excluded
    # rather than the name compared.
    taken = conn.execute(
        "SELECT name FROM team_members WHERE name=? AND id<>?",
        (new_name, row["id"])).fetchone()
    if taken is not None:
        conn.close()
        return {"error": "%s is already an Engineer." % taken["name"],
                "code": "name_taken"}, 409
    if new_name == old_name:
        conn.close()
        return {"status": "ok", "id": row["id"], "name": old_name,
                "renamed": False}, 200
    conn.execute("UPDATE team_members SET name=? WHERE id=?",
                 (new_name, row["id"]))
    moved = conn.execute(
        "UPDATE transactions SET team_member=?"
        " WHERE team_member=? COLLATE NOCASE",
        (new_name, old_name)).rowcount
    conn.execute("UPDATE clients SET member=? WHERE member=? COLLATE NOCASE",
                 (new_name, old_name))
    conn.commit()
    conn.close()
    _log_event("member.renamed",
               "#%d%s%s%s%s" % (row["id"], "  ", old_name, _RENAMED_SEP,
                                new_name),
               actor=authorised_as or "Admin", level="warn")
    return {"status": "ok", "id": row["id"], "name": new_name,
            "was": old_name, "renamed": True, "transactions": moved}, 200
