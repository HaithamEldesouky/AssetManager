# 014 - Storekeeper: the Server URL can be changed while the server is unreachable

**Type:** feature · **Depends on:** 012 (same `common.py` line, and the same decision)

## What is asked

Allow the Server URL to be changed even when the server is offline.

## Where it stands today

Server Settings asks for the admin password and checks it with
`common.verify_admin_password` (`storekeeper_app.py:2430`), which is a POST to the server.
With the server unreachable the check raises and the window cannot be opened - so the one
field that could point the app at a server it can reach is behind a check that needs a
server it can reach.

## Scope

- When the server cannot be reached, allow the Server URL to be edited and saved, and say
  on the window that no password could be checked.
- **Only the URL.** Everything else on that window keeps its check.
- Match whatever 012 settles for the Notifier - this is the same question in the second
  app, and two different answers to it is precisely what rule 10 exists to prevent. If the
  offline path becomes shared code it belongs in `common.py`.

## Why it is sequenced behind 012

Not a code dependency - a cascade one. Both tickets land in the `common.py` row of the
architecture table in `CLAUDE.md`, which is a single ~1900-character line; git merges by
line, so two branches editing it do not merge, they conflict over the whole line.
`docs/agents/ticket-workflow.md` says sequence rather than start both.

## Cascade

- The Storekeeper's **Server Settings** bullet in `CLAUDE.md`, and the `common.py` row if
  the helper lands there.
- Run `client-checks.py`.
