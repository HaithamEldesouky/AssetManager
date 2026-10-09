# 015 - Bug: the admin password is refused in the current-password field

**Type:** bug · **Depends on:** nothing

## What happens

Changing an Engineer's password with the **admin password** typed into the *current
password* field does not work.

## What the code says

`POST /auth/change_password` (`server.py:3955`) looks correct on its face:

    own = password_matches(current, row["password_hash"])
    if not (own or _admin_password_ok(current)):
        return ... "code": "bad_password", 401

The admin password is accepted, and which of the two opened the door decides whether
`must_change_password` is armed (admin) or cleared (their own).

**But there is a check above it that fires first** (`server.py:3967`):

    if not row["password_hash"]:
        return ... "code": "no_password", 409

So an Engineer who has **no Own Password yet** is refused before any password is examined,
including the admin password. That is deliberate - the endpoint changes an Own Password and
never creates one, so an Admin at a Notifier cannot stand a permanent first one up over the
network - but from the seat of whoever is typing, "I used the admin password and it did not
work" is exactly what it looks like.

## What to do

1. **Reproduce first, and say which case it is.** Two candidates, and they need different
   fixes:
   - the Engineer had no Own Password → the `no_password` 409 above. Working as designed;
     the fix is the *message*, which should name the remedy (an Admin sets the first one
     from the Server GUI's Engineer Passwords window) instead of reading like a refusal of
     the password that was typed.
   - the Engineer had one and the admin password was still refused → a real defect in
     `_admin_password_ok` on this path. Check the pre-ADR-0008 bare SHA-256 branch: if the
     stored admin hash is still in the legacy format and the in-place rewrite is what fails,
     the refusal would be wrong. `server-checks.py` already has a group for that rewrite.
2. Fix that case only. Do not widen the endpoint to create a first password - that is the
   thing the 409 exists to prevent.
3. Whatever the cause, the **client** shows the server's words
   (`notifier_app.py` `OwnPasswordWindow._submit`), so a clearer server message reaches the
   engineer with no client change.

## Cascade

- The `POST /auth/change_password` row of the API table in `CLAUDE.md` if a refusal's
  wording or its `code` changes.
- Add the case to `server-checks.py`'s Own Password lifecycle group - it already asserts
  the admin password is the reset path, so this is the case that group was missing.
