# 108 - A popup answered elsewhere closes and says so

**Type:** feature · **Depends on:** 106, 107 · **Issue:** [#284](https://github.com/HaithamEldesouky/AssetManager/issues/284)

## Finding

The Notifier polls `GET /pending/<member>` (default every 15 s) and
`PopupQueue.arrived()` in `notifier_pending.py` only adds Transactions it has not
seen. Nothing removes one that has left Pending. The desktop may be showing a
popup - or holding one in its queue - for a Transaction already Confirmed,
Rejected or Cancelled elsewhere (from the Dashboard, another desktop, or the
Storekeeper cancelling it). Verify against the code first how a popup for a
Transaction that is no longer Pending behaves today; the answer decides how much
of this ticket is new.

An answer the desktop held offline for that Transaction already resolves
correctly: a 409 `not_pending` is treated as `SENT` (`notifier_pending.py`).
Keep that.

## Scope

- On each poll, a Transaction that is open as a popup or queued, and is absent
  from the new Pending list, is dropped: an open popup closes, a queued one is
  removed.
- Then a short, non-modal notice names what happened: "Answered elsewhere".
  Read the row via the history reader the Notifier already uses; one request per
  dropped Transaction.
- The decision logic belongs in `notifier_pending.py` (no tkinter, returns what
  should happen); `notifier_app.py` performs it - the split #208 set.
- 107 is a dependency only because both touch `notifier_app.py` and the same
  `docs/reference/apps.md` Notifier description; sequence, do not run together.

## Coverage

Client suite: `notifier_pending` returns a drop for a queued id absent from a
new poll, and does not drop one still present; a deferred popup (#194) that
leaves Pending is dropped rather than re-shown.

## Cascade

- `docs/reference/apps.md`: the Notifier popup description.

## Verification

- `ast.parse()` every edited Python file.
- Run a Notifier from source; with its popup open, confirm the same
  Transaction from another client; within one poll the popup closes and the
  notice appears.
- `py -3.12 tools/gate.py` passes.

## Done when

No desktop popup stays up for a Transaction that is no longer Pending, and the
Engineer is told where it was answered.
