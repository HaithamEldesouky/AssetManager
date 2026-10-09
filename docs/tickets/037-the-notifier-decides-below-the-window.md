# 037 - The Notifier decides below the window

**Type:** refactor · **Depends on:** nothing in code; sequenced behind 036 for the cascade · **Found by:** architecture review, Sep 2026 · **Issue:** [#208](https://github.com/HaithamEldesouky/AssetManager/issues/208)

## Finding

The Notifier's decision logic only exists inside Tk callbacks. `_confirm` (595) and
`_reject` (612) call `_send_answer` (519), which performs the request and mutates the
pending queue in one act. The popup ordering and the offline hold live in the same place:
`_popup_queue` (4001), `_cmd_queue` (4015), and the scheduling at 4348-4454.

There is no interface below the widget, so the only way to assert any of it is to open a
real window and measure it. `docs/CODING_STANDARDS.md:212-248` already records what that
costs: #204 ran one unchanged group three times for green, red, green, and read 67, 64,
60, 58 and 56px on different runs - and notes the **green** runs were the wrong ones,
hiding a real clipped control.

That is not a bad suite. It is a suite asserting through the only interface there is.

**This is the ticket behind "every feature doesn't work very well".** A new confirmation
rule cannot be checked except by eye, so it ships unchecked.

## Scope

One new module holding the Pending decisions, with no tkinter import.

1. **It takes a Transaction and an answer, and returns what should happen.** It does not
   perform the request and does not touch a widget. Return results, do not produce side
   effects - the caller performs them.

2. **It owns:** confirm, reject, the offline hold, and the order the popup queue is
   drained in.

3. **The widgets call it and draw the result.** `_confirm` and `_reject` become two lines
   each.

4. **`tools/client-checks.py` gains a group that calls it directly**, with no root window
   and no display. Every assertion carries its negative half, per
   `CODING_STANDARDS.md:212`.

**Not a race fix.** The review initially flagged `_cmd_queue` as unsafe across threads. It
is not: the drain at `notifier_app.py:4742-4744` takes `batch = self._cmd_queue[:]` then
`del self._cmd_queue[:len(batch)]`, which is safe against tail appends, and CPython's list
operations are atomic. Do not "fix" it.

## Not in this ticket

- The Storekeeper. It has no pending queue.
- The Remote Admin window's blocking calls - that is 038's neighbour, filed separately if
  wanted.
- Any change to what an engineer sees.

## Cascade

- `CLAUDE.md` - "The files" table gains the module.
- `docs/reference/architecture.md` and `docs/reference/apps.md` - the Notifier's rows.
- `tools/bundle-client.ps1` `$Payload` **and** `installer.py:49` `SOURCE_FILES` - both
  lists name every client module. A new one missing from either ships a client that cannot
  start. This is the cascade row `CLAUDE.md` names for a shared client module.
- `docs/CODING_STANDARDS.md:12-22`.

## Verification

- `ast.parse()` every file touched.
- `py -3.12 tools/gate.py --all`.
- The new checks must run with no display at all. If they need a root window, the seam is
  in the wrong place.
- By hand: confirm and reject from the popup and from the Dashboard, with the server up
  and with it down, and confirm the offline hold still replays on reconnect.

## How it landed

`notifier_pending.py`, 317 lines, imported by `notifier_app.py` at module level under
its own name rather than `as pending` - `_poll_once` binds a local called `pending`
for what `GET /pending/<member>` answered, and the alias would have shadowed the
module inside the one function that had to reach it.

Scope §1 asked for a module that "takes a Transaction and an answer and returns what
should happen". Three of the four pieces are plain functions over the answer entry -
`request()` says where it goes and what it carries, `classify()` reads what came back
into `sent`/`hold`/`refused`, `held()` says whether to keep it and `note()` what the
System Log line says - and the app performs the call between `request` and `classify`.
Two pieces needed state rather than a function, and are classes for that reason and no
other: `Flush`, a three-method state machine over the held queue that the caller feeds
one outcome at a time (the alternative was handing the whole queue a callback, which
would have put the request back inside the module), and `PopupQueue`, which owns the
queue, the ids this process has already offered and the gap a deferred popup waits
out. Those three were `_popup_queue`, `notified_ids` and `_popup_hold_until` on the
app; they moved together because they are one invariant - a Transaction dropped from
the queue without leaving the seen set is an engineer who is never asked again, which
is the failure #194 was about.

**The event names stayed at the call sites.** The obvious shape was for the module to
return the System Log entry whole, name included. It cannot: `tools/cascade-audit.py`
derives the emitted event names by reading string literals out of `log_event(...)`
calls, and five names - `transaction.confirmed`, `transaction.rejected`,
`transaction.dismissed`, `answer.buffered`, `answer.refused` - would have become
documented rows the audit reports as written by nothing. So `note()` decides what a
line *says* and the name is passed in by `_confirm`/`_reject`, which is also the
honest split: logging is a side effect, and this module performs none.

`_confirm` and `_reject` are two lines each as §3 asked, over one new `_answer` that
holds, logs, dismisses and polls - the four side effects both of them shared verbatim.
`_dismiss` kept its name and its one remaining job, closing the popup on screen;
stripping the queue and clearing the seen id are `PopupQueue.resolved`'s, one act
rather than the `notified_ids.discard` + `_dismiss` pair each caller used to do.

**The clock is an argument.** `PopupQueue(repeat_ms, now=time.monotonic)`, and the new
group hands it a list to advance by hand. Without it the #194 assertions are a gate
sleeping through a fifteen-minute default, or a gate asserting a shorter gap than the
product has; with it, "a wake a hair in front of the deadline asks again rather than
dropping the Transaction" is three lines and no waiting.

The new group, `check_the_notifier_decides_below_the_window`, calls `tk_or_skip()`
never and builds no app: 40 assertions on a machine with no desktop. Its first two
read the module's own import list and assert it *exactly* (`collections`, `common`,
`time`) rather than asserting the absence of `tkinter`, which is the negative half -
an absence check over a file the reader failed to parse reports a clean run for ever,
which is the trap `CODING_STANDARDS.md:212` names. The existing
`check_the_notifier_holds_an_answer_the_server_would_not_take` was left alone: it
drives the app's performing half through a fake `_App`, and that is still a thing worth
asserting now that the deciding half is asserted beside it.

**Cascaded:** `installer.py`'s `SOURCE_FILES["notifier"]`; `tools/bundle-client.ps1`,
where `$Apps.<key>` gained an `Extra` list, since a Notifier-only module in the shared
`$Payload` would have the Storekeeper's zip carrying and installing a file it never
imports; `tools/cascade-audit.py`, whose two-payload-lists check now reads `Extra` into
the staged set and whose `SHIPS` regex names the new file; `tools/dev-run.ps1`'s
notifier staging list, which the audit derives from that app's module-level imports;
`tools/gate.py`'s client row; `tools/client-checks.py`'s staging list, which loads the
module *before* `notifier_app.py` so the app's own import finds the staged copy;
`CLAUDE.md`'s file table and its cascade row for a client module, which now covers one
app's as well as a shared one; `docs/reference/architecture.md`,
`docs/reference/apps.md` and `docs/CODING_STANDARDS.md` ("Where code goes", "Headless
safety").

**Not cascaded:** no `APP_VERSION` bump - a refactor with no behaviour change, and the
release that ships it stamps it. No new System Log event, so
`docs/system-log-events.md` and `EVENT_SENTENCES` are untouched. No database column, no
endpoint shape, no new file written beside an app.

**Not done, as the ticket asks:** the command queue. `_drain_commands` takes
`batch = self._cmd_queue[:]` and then `del self._cmd_queue[:len(batch)]`, which is safe
against the poll worker's tail appends, and it is unchanged.

