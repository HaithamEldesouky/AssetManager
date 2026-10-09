# 018 - The `/clients` invariant needs narrowing, and the System Log window is unmeasured

**Type:** test coverage · **Depends on:** nothing · **Found by:** the 009-015 gate run (CHECK 6)

## Finding 1 - two gates now disagree

    [FAIL] check-in is still the only thing under /clients: got ['/clients/log'], wanted []

`tools/server-checks.py:4462` asserts that nothing but `/clients/checkin` may live under
`/clients`. Ticket 011 added `POST /clients/log`, which is documented in the API table and
which `cascade-audit.py`'s routes-vs-table check passes. So one gate says the route is
properly recorded and the other says it may not exist.

**The invariant is right and its wording is too wide.** What ADR-0005 and the API table
actually protect is that the **registry is never published**: "There is deliberately no
`GET /clients`" - the table is a map of hostnames, Windows accounts and addresses of
machines on the internal network, and the Server GUI reads it rather than serving it. A
write-only POST does not publish anything.

So narrow the assertion to what it was defending:
- **no route under `/clients` may serve a `GET`** - that is the line that must never move;
- the POSTs are an allow-list of the documented two, `/clients/checkin` and `/clients/log`,
  so a third still fails and has to be argued for deliberately.

Do **not** simply delete the check or add `/clients/log` to an ignore list: the first
throws the protection away and the second makes the next addition silent.

## Finding 2 - the System Log window produced no measurement line at all

The gate's window-size group printed nothing for it. Either the harness never opens it or
it is resizable on both axes, in which case the group reports a drag rather than a
measurement. Both are "unmeasured", not "passing", and this window is new in 011.

- Establish which it is, then make it measured: add it to the group's opener list if it is
  missing, and if it is resizable on both axes say so in the group's output rather than
  printing nothing - a window that silently produces no line is indistinguishable from one
  the harness forgot.

## Verification

Both are in `tools/server-checks.py`, which cannot run in the cloud container. The
`/clients` half can be exercised by listing `M.app.url_map` alone; the window half needs a
display.
