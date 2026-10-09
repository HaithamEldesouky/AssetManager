# 010 - Server GUI: the admin manages RBAC profiles, and sensitive actions become permissions

**Type:** feature · **Depends on:** 009 · **Blocks:** 012, 013

## What is asked

The admin manages permission profiles from the server, and sensitive access is audited and
added to the permission list.

## Where it stands today

`PERMISSIONS` in `server.py:3017` holds **two** names:

    view_all_history   - the Notifier Dashboard shows every engineer, not only their own
    open_settings      - Notifier Settings opens with the engineer's own password

`PERMISSION_LABELS` in `storekeeper_app.py:57` mirrors them (rule 8), and the only place a
profile is edited today is the **Storekeeper's** Add Engineer dialog. `profile` is
`default` or `custom`; `DEFAULT_PROFILE_PERMISSIONS` is empty, and `_member_permissions`
only consults the stored list on a custom profile.

## Scope

1. **Move profile editing to the server**, into 009's Manage Users window: per-Engineer
   Default/Custom and the per-permission checkboxes, admin password required.
2. **Audit what is sensitive and currently ungated, then add only what gates real
   behaviour.** Rule 8 is explicit: a permission that gates nothing must not exist,
   because an admin ticks it and believes something changed. Candidates to assess, each
   with the question "is this behaviour actually reachable by an Engineer?":
   - the Notifier Dashboard's Confirm / Reject (today any Engineer resolves their own)
   - the Storekeeper's Export to Excel, Bulk Scan, and Cancel
   - anything the Storekeeper does at all, which is an install rather than a login
   Write down for each whether it is gated by a password, by a permission, or by nothing.
   **The endpoints that are unauthenticated on purpose (ADR-0002) are not in scope** -
   `POST /transactions`, `/confirm`, `/reject` stay unauthenticated, and a permission that
   pretended otherwise would be a lie the server does not enforce.
3. Every new name is enforced **on the server**, not only hidden in a client: the server
   already rejects an unknown permission name at `POST /members`, and a client left behind
   by a change must fail at the endpoint naming the offender.

## Cascade (rule 8 - `cascade-audit.py` checks this)

- `PERMISSIONS` in `server.py` **and** `PERMISSION_LABELS` in `storekeeper_app.py`, even
  though 013 is removing that dialog - until 013 lands they must agree.
- The count `CONTEXT.md` states in words.
- The Notifier's **Access profile** bullet and the Storekeeper's **Engineers from server**
  bullet in `CLAUDE.md`.
- `POST /members` in the API table if the shape changes (it must stay additive).
- Run `cascade-audit.py` - it compares all three copies.

---

## Audit

Scope 2 asked which sensitive actions are gated, and by what. The table below is the
answer, read off the code rather than off memory. **Verdict: no new Permission
qualifies.** `PERMISSIONS` stays at two, and this ticket ships part 1 alone. The
reasoning is below the table, and it is not "there was nothing sensitive" - it is that
a Permission is the wrong instrument for every one of the ungated things, and rule 8
forbids adding a name that only hides a button.

### What gates what, today

| Action | Where | Gated by | Enforced where |
|---|---|---|---|
| Notifier popup Confirm / Reject | `POST /confirm/<id>`, `POST /reject/<id>` | **nothing** | nowhere, on purpose (ADR-0002) |
| Notifier Dashboard Confirm / Reject | same two endpoints | **nothing** | nowhere, on purpose (ADR-0002) |
| Notifier Dashboard, own records | `GET /transactions?member=` | **nothing** | nowhere - the endpoint is open |
| Notifier Dashboard, every Engineer | `view_all_history` | **a Permission** | **client only** - see below |
| Notifier Settings (Server URL, Assigned User, Poll Interval) | `verify_password` | admin password, **or** own password + `open_settings` | server answers `/auth/verify` with the profile; the client obeys |
| Notifier Change My Password | `POST /auth/change_password` | that Engineer's **current** Own Password, or the admin password | server (`_authorise` is never reached; the current password is checked against *that* row) |
| Notifier theme | tray submenu | **nothing**, deliberately | n/a - changes what this screen looks like |
| Notifier Reset Identity / Log Off | a queued Client command | **admin password** at the Server GUI | server (`_queue_command`) |
| Storekeeper Submit, Bulk Scan Mode, offline flush | `POST /transactions` | **nothing** | nowhere, on purpose (ADR-0002); the lookup sheet (rule 6) is the only check |
| Storekeeper Export to Excel | `GET /export` | **nothing** | nowhere - the endpoint is open |
| Storekeeper history, search, filters | `GET /export`, `GET /transactions` | **nothing** | nowhere - the endpoints are open |
| Storekeeper Cancel, Pending row | `POST /transactions/cancel` | the **`storekeeper_can_cancel` switch** | server, re-read from `server_config.json` on every request |
| Storekeeper Cancel, Confirmed row | same | **admin password** | server (`_cancel_transaction`) |
| Storekeeper Add / Delete Engineer | `POST /members`, `POST /members/delete` | **admin password** | server (`_save_member`, `_delete_member`) |
| Storekeeper Access Profile + Permissions | `POST /members` | **admin password** | server (`_save_member`; an unknown name is a 400) |
| Storekeeper Server Settings | `verify_admin_password` | **admin password**, never an own password | server (`POST /admin/verify`) |
| Storekeeper theme | header button | **nothing**, deliberately | n/a |
| Server GUI, everything that writes | Add Transaction, Modify, Cancel, Manage / Delete Records, Manage Users, Engineer Passwords, Capability Passwords, Lookup Sheet, Import Archive | **admin password**, four of them delegable to a **Capability Password** (ADR-0006) | server - the console is the server process, and each goes through the same helper its endpoint does |
| Server GUI, Display Settings / Database Location / SSL Certificate / Copy URL | - | **nothing**, deliberately | n/a - physical access to that console, and the certificate is public |
| `GET /members` | anyone on the network | **nothing** | nowhere - the Engineer list, who is Auto-Approve, and who holds an Own Password |
| `GET /lookup`, `GET /lookup/file`, `GET /asset_types` | anyone on the network | **nothing** to read; **admin password** to write | server, on the write half only (rule 11) |
| `GET /stats`, `/health`, `/version`, `/cert`, `/download/installer` | anyone on the network | **nothing**, deliberately | n/a |
| `POST /clients/checkin` | any Client | **nothing**, deliberately (ADR-0005) | n/a |

### Why nothing new qualifies

1. **The transaction endpoints are open on purpose and a Permission cannot close them.**
   `POST /transactions`, `POST /confirm/<id>` and `POST /reject/<id>` carry no credential
   by design (ADR-0002): a Notifier holds nothing to prove it is the Engineer named in the
   URL, and an Engineer who cannot confirm is an Engineer the store stops being able to
   record against. A `confirm_own_transactions` name would be checked by the *client that
   is asking* and by nothing else, which is exactly the thing rule 8 forbids - an Admin
   unticks it, the button disappears from one window, and `curl` confirms the Transaction
   anyway.

2. **Nothing the Storekeeper does can be gated by a Permission at all.** The Storekeeper
   is an installation, not a login: no name and no credential reaches the server on any
   call it makes, so there is nobody for a `team_members` row to be about. Export, Bulk
   Scan and the history are open for that reason and not by oversight. The one thing that
   *is* gated there is gated the only way it can be - `storekeeper_can_cancel` is a switch
   on the server about what the network may do, re-read from disk per request, and the
   admin password overrides it. That is the existing answer to "the Storekeeper should not
   be able to do X", and it is a server switch rather than a Permission precisely because
   there is no identity to hang a Permission on.

3. **The sensitive *writes* are already at the strongest gate there is.** Everything that
   changes the Engineer list, a password, a Transaction after the fact, the lookup sheet
   or the server's own configuration takes the **admin password**, checked on the server,
   in a helper the console and the endpoint share. A Permission below that would be a
   weaker credential for the same action, i.e. a way past it. Four of the console actions
   are delegable, and that is a **Capability Password** (ADR-0006), which is a different
   instrument on purpose: it opens one action at one console and reaches no endpoint.

4. **The open *reads* are open because a Client has to read them before anybody has
   authenticated.** `GET /members` is how the Notifier's setup wizard and the installer
   offer an Engineer to be configured as, and how `fetch_permissions` reads a profile -
   all of which happen before any password is typed. Gating it on a Permission is circular:
   the caller would have to prove which Engineer it is in order to find out which Engineers
   exist. What it discloses is already bounded - names, Auto-Approve, the profile, and
   booleans for the two password states, never a hash.

5. **Two findings worth recording, neither of which is a Permission.**
   - `view_all_history` is a **display** decision and always was: `GET /transactions` takes
     a `member` filter and enforces nothing, so an Engineer who unticked it in their own
     client, or a `curl`, reads the whole store either way. It stays because it gates real
     behaviour an Admin wants to control - which Dashboard an Engineer is shown - not
     because it keeps a secret. `CLAUDE.md` already says so; this audit is the evidence.
   - With `view_all_history` on, the Dashboard's **Pending** tab lists every Engineer's
     pending rows, so that Engineer can Confirm or Reject somebody else's from the queue
     card. The server accepts that from anyone regardless (point 1), so this is not a hole
     a Permission would close; if it is unwanted it is a **display** fix - scope the
     Pending queue to `current_user` even when the History tab is widened - and belongs in
     a ticket of its own rather than in a permission name.

### What was added instead

Part 1 only: Access Profile and the per-Permission ticks moved onto the Engineer's card in
the Server GUI's **Manage Users** window, admin password, writing through `_save_member` -
the same helper `POST /members` forwards to, so the console and the wire cannot disagree.
`PERMISSIONS` is unchanged at two names, `PERMISSION_LABELS` in `storekeeper_app.py` is
unchanged, and `CONTEXT.md` still says there are two.

A `PERMISSION_LABELS` table was added to `server.py` beside `PERMISSIONS` - the checkbox
captions the new form draws. It is **not** a second list of names: the form loops over
`PERMISSIONS` and looks a caption up, so a name with no caption is still offered as itself.
`cascade-audit.py` holds it to `PERMISSIONS` so the two cannot drift.
