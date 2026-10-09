# 013 - Storekeeper: creating an Engineer only, no password and no permissions

**Type:** refactor · **Depends on:** 009, 010

## What is asked

Remove engineer management from the Storekeeper. Leave the ability to create a user, but
without setting a password or permissions.

## Where it stands today

Under the Engineer field sit **➕ Add New Engineer** and **🗑 Delete Engineer**
(`storekeeper_app.py`, the dialog around line 1327). Add New Engineer carries an
Auto-Approve checkbox, an **Access Profile** choice with per-permission checkboxes fed by
`PERMISSION_LABELS` (`storekeeper_app.py:57`), and an optional **Engineer's Own Password**
which the endpoint marks Temporary (ADR-0009).

## Scope

- Keep: creating an Engineer - name, and Auto-Approve if you judge it belongs with
  creation rather than with management (say which you chose and why).
- Remove: the Own Password field, the Access Profile choice and the permission checkboxes,
  and `PERMISSION_LABELS` with them **once nothing else reads it**.
- **Delete Engineer**: the ticket says "remove engineer management". Decide explicitly
  whether deletion goes too - it removes a name from a dropdown and keeps all history, so
  it is nearer to creation than to permission-granting. Recommended: it goes, since 009
  gives the server the window for it.
- `POST /members` itself is **unchanged**: omitted fields already keep their current value,
  so a Storekeeper that stops sending `member_password` and `permissions` needs no endpoint
  change and an older client mid-rollout still works.

## Why it is blocked

Both capabilities must exist on the server **before** they leave the Storekeeper, or the
system loses them in between: 009 provides the window, 010 moves profile editing into it.
Merging this first would leave nobody able to set an Engineer's password except the Server
GUI's Engineer Passwords dialog, and nobody able to set permissions at all.

## Cascade (rule 8)

- `PERMISSION_LABELS` is half of a pair `cascade-audit.py` checks against `PERMISSIONS`.
  If it goes, that check has to be told - do not leave the audit asserting a file it no
  longer lives in.
- The Storekeeper's **Engineers from server** bullet in `CLAUDE.md`, rule 7's sentence
  about the admin setting an Own Password "from the Storekeeper's Add Engineer dialog",
  and ADR-0009 if it names that dialog as the place.
- Run `cascade-audit.py` and `client-checks.py`.
