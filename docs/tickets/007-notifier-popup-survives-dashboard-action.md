# 007 - Bug: the Notifier popup survives a confirm/reject made from the Dashboard

**Type:** bug · **Depends on:** nothing

## What happens

An engineer confirms or rejects a transaction in the Dashboard's history, and the popup for
that same transaction is still on screen - and can be confirmed or rejected a second time.
A popup still queued behind the current one appears later for a transaction that is already
resolved.

## Why

`notifier_app.py`: the Dashboard's `_do_confirm` / `_do_reject` (~839 / ~848) add the id to
the Dashboard's own `_busy` set and call the app's `_confirm` / `_reject` (~1385 / ~1391),
which post to the server and re-poll. Nothing touches `self._current_popup` or
`self._popup_queue`, so a popup already showing that id stays up, and a queued one is still
shown by `_show_next_popup` when its turn comes.

`_busy` is the Dashboard's own state and does not reach the popup queue - the two views
each track what they have acted on and neither tells the other.

## Scope

- When a transaction is resolved from any source, dismiss the popup showing that id and
  drop it from `_popup_queue`, letting `_popup_finished` advance the queue as usual.
- Do it in `AssetNotifier`, which owns `_current_popup` and `_popup_queue` - the Dashboard
  already routes through `on_confirm` / `on_reject`, so the callback it already calls is the
  place.
- **Stay on the Tk thread.** The Dashboard's buttons are already on it; a popup destroyed
  from a worker is the failure `_cmd_queue` exists to avoid. Do not marshal with `after`
  from a poller.
- Nothing here may stop a transaction being confirmed - a popup that is dismissed must
  leave the queue able to show the next one.

## Cascade

- `CLAUDE.md` -> Notifier App -> the **One at a time (v1.6.1)** bullet, which describes the
  queue this changes.
- Run `python tools/client-checks.py`.
