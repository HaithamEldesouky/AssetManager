# 008 - client-checks.py covers the popup dismissal 007 fixed

**Type:** test coverage · **Depends on:** 007 (merged)

## Why

`docs/CODING_STANDARDS.md` says a bug fix gets the check that would have caught it. 007 -
the Notifier popup surviving a confirm/reject made from the Dashboard - shipped without
one: adding a group would have meant cascading the `tools/client-checks.py` section of
`CLAUDE.md`, which three parallel tickets were editing at the time, so it was left out
rather than widening the change unasked.

## Scope

- A `check_*` group in `tools/client-checks.py`, in the idiom of the group that already
  stubs the Notifier's Temporary-Own-Password replacement form: stub the popup and assert
  that resolving a Transaction through `on_confirm` / `on_reject` closes the popup showing
  that id, removes queued entries for it, leaves an unrelated id alone, and still lets
  `_popup_finished` advance the queue.
- Nothing about the app changes. This is the missing check, not a second fix.

## Cascade

- The `tools/client-checks.py` section of `CLAUDE.md` - it lists what each group covers.
