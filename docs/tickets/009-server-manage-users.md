# 009 - Server GUI: a Manage Users window for Engineers, Admin and the Storekeeper

**Type:** feature · **Depends on:** nothing · **Blocks:** 010, 013

## What is asked

One place on the server to manage the people this system knows: the Engineers, the
Admin, and the Storekeeper.

## Where it stands today

There is no such place, and the three are not the same kind of thing:

- **Engineers** are rows in `team_members`, managed from the **Storekeeper's** Add /
  Delete Engineer dialogs (`POST /members`, `POST /members/delete`) and their Own
  Passwords from the Server GUI's **Engineer Passwords** window.
- The **Admin** is not a user at all - it is one password hash in `admin_config.json`,
  plus four capability passwords (ADR-0006). Nobody is named.
- The **Storekeeper** is not a user either. `Storekeeper User` is a **default column value**
  on `transactions.storekeeper`, and the app is identified by its install, not by a login.

So this ticket is not "collect three lists into a window" - it is deciding whether Admin
and Storekeeper become identities. **Settle that before writing code**, because it decides
the schema:

- **A (recommended, smaller):** the window manages **Engineers** as first-class rows and
  *shows* the Admin and the Storekeeper as what they are - a credential and an install -
  linking to Change Admin Password and to Connected Clients. Nothing new in the schema.
- **B (bigger):** `team_members` gains a `role` column (`engineer` / `admin` /
  `storekeeper`) and all three become rows. This is a real identity model: it needs a
  migration (`007_member_role`), a decision about what an `admin` row's password means
  against `admin_config.json`'s hash, and it touches every predicate that reads
  `team_members` today - the Engineer dropdowns, `GET /members`, Auto-Approve, the
  Notifier's own-profile read.

## Scope (shape A; re-scope if B is chosen)

- A **Manage Users** window in the Server GUI, reached from Change Admin Password beside
  Capability Passwords and Engineer Passwords - that is the window an admin opens to think
  about who holds what.
- Engineers: add, rename-free delete (history is kept, as `POST /members/delete` already
  does), Auto-Approve, Own Password state (the three states Engineer Passwords already
  derives), and profile once 010 lands.
- Admin and Storekeeper: shown with what they actually are, and the control that changes
  each - not invented rows.
- **Admin password**, checked with `_admin_password_ok` directly rather than through
  `_authorise`: whoever can add an Engineer or set an Own Password can then be that
  Engineer (the reasoning ADR-0009 already gives for Engineer Passwords), so this is not a
  fifth Capability.
- Write through the existing helpers - `_set_member_password` and whatever `POST /members`
  goes through - so the console and the wire cannot disagree.
- Size with `ui_kit.fit`, footer packed `side="bottom"` before the form.

## Cascade

- `CLAUDE.md`: the Server GUI section (a new bullet), and the "Ten dialogs here call
  `ui_kit.fit`" sentence plus the `ui_kit.py` architecture row's window counts - **re-derive
  both from the source**, do not increment the written number.
- If shape B: the `team_members` schema block, `init_db()`'s idempotent `ALTER TABLE`,
  migration `007`, `GET /members` in the API table, and every client that reads it.
- `CONTEXT.md` glossary if "User" becomes a domain term distinct from Engineer.
- Run all three gates.
