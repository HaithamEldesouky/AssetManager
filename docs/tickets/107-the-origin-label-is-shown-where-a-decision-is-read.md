# 107 - The Origin label is shown where a decision is read

**Type:** feature · **Depends on:** 106 · **Issue:** [#283](https://github.com/HaithamEldesouky/AssetManager/issues/283)

## Finding

After 106 every newly decided Transaction carries `origin` on the wire, but no
window reads it. The requirement is that an Auto-Approved or Auto-Accepted answer
is visible as such wherever a decided Transaction is read.

## Scope

Show the Origin beside the state wherever a decided Transaction is read:

- Notifier (`notifier_app.py`): the history view and the Dashboard - e.g.
  `Confirmed (auto)`.
- Server GUI: Manage Records (`gui_records.py`) - a state column suffix or an
  Origin column, whichever matches how that table already shows state.
- `desktop` and NULL show no suffix: the label exists to mark the unusual case.
- A server that predates 106 sends no `origin`; the Notifier must show exactly
  what it shows today.

## Not in this ticket

- The popup closing when answered elsewhere (108).
- The Storekeeper's history. Add it only if the Storekeeper already shows the
  confirm state per row; otherwise leave it.

## Coverage

Client suite: a row with `origin: "auto"` renders the suffix; a row with no
`origin` key renders as before. Server suite if Manage Records has a check.

## Cascade

- `docs/reference/apps.md`: the Notifier history/Dashboard description and the
  Manage Records description.
- If the Notifier changes a shared function in `common.py`, the `common.py` row
  in `docs/reference/architecture.md` - a long line; sequence against any other
  open ticket touching it.

## Verification

- `ast.parse()` every edited Python file.
- Run a Notifier from source against a server with 106; reject one Transaction
  from a second client and see the label.
- `py -3.12 tools/gate.py` passes.

## Done when

A Transaction with Origin `auto` reads as such in the Notifier
history, the Dashboard and Manage Records.
