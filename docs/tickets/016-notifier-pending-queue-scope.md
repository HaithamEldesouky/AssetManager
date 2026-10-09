# 016 - Bug: with view_all_history, the Notifier's Pending queue offers another Engineer's rows

**Type:** bug · **Depends on:** nothing · **Found by:** 010's audit

## What happens

An Engineer whose profile grants `view_all_history` opens the Dashboard. The **Pending**
tab's queue cards are built from the same widened row set as the history table, so they
list Transactions recorded against *other* Engineers - each with a Confirm and a Reject
button. Clicking either resolves somebody else's Transaction, and the server accepts it.

## Why this is a display fix and not a permission

The server accepts `POST /confirm/<id>` and `POST /reject/<id>` from anyone, deliberately
and permanently - ADR-0002. So nothing here is a hole that a new permission could close:
a permission over those endpoints would be enforced only by the client that chose to ask,
and `cascade-audit.py` would be asserting a rule the server does not hold. 010's audit
settled that and added no name for it.

What is actually wrong is narrower and fixable: `view_all_history` is meant to widen what
an Engineer can **see**, and it is widening what they are **offered to act on**. The
Dashboard's own note already says "Confirm and Reject here do the same as the popup" - and
the popup only ever shows that Engineer's own pending Transactions.

## Scope

- Scope the **Pending queue** to `current_user` regardless of `view_all_history`; leave
  the **history table** widened, which is what that permission is for.
- The Engineer column and the widened table stay exactly as they are.
- One-line-ish change in `_paint_queue` (`notifier_app.py` ~line 739), which already
  filters on status and `self._busy`.

## Cascade

- The Notifier's **Access profile** bullet in `CLAUDE.md`, which describes what
  `view_all_history` widens - it should say the queue is not part of it.
- `tools/client-checks.py`: the Dashboard is already built in the window-size groups with
  `see_all` both ways, so the fixture exists; assert the queue's row count against an
  engineer-filtered set.
