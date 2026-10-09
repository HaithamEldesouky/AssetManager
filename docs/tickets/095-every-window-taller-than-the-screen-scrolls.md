# 095 - Every window taller than the screen scrolls

**Type:** feature · **Depends on:** 091 (#266), 093 (#268), both merged · **Issue:** [#270](https://github.com/HaithamEldesouky/AssetManager/issues/270)

## Finding

`ui_kit.fit` clamps a window's height to `winfo_screenheight() - 80`, and `pack` gives
the shortfall to whatever it served last. On a 1366x768 laptop that is 688px. A footer
packed from the bottom survives the clamp - `survives_a_short_screen` in
`tools/client_checks/stage.py` proves that much - but the form above it is cut, and the
fields in the cut are not reachable by any drag or scroll.

`ui_kit.ScrollRegion` answers exactly this, and four windows already carry the answer:
Notification Rules (`gui_mail.py`), the Notifier's Remote Admin Notification Rules
(`notifier_remote.py`), and Manage Users and Capability Passwords (`gui_users.py`, a
canvas inlined before the class existed).

Measured on `main` at 8dd0ecf by wrapping `ui_kit.fit` in both check suites and reading
`winfo_reqheight()` at every call. Heights are at the suites' own data volume; a window
that grows with its data only grows from here.

| Window | Opener | Requested | Scrolls |
|---|---|---|---|
| Asset Sync | `gui_proposals.py` `asset_sync` | 965px | no |
| Server Settings | `gui_settings.py` `server_settings` | 943px | no |
| Remote Admin | `notifier_remote.py` `_open_with` | 931px | no - two inner lists scroll, the window does not |
| Mail Settings | `gui_mail.py` `mail_settings` | 868px | no |
| Add Transaction | `server_gui.py` `add_transaction` | 762px | no |
| Modify Transaction | `gui_records.py` `modify_selected` | 674px | no - 14px under |
| Correct Transaction | `notifier_remote.py` | 657px | no - 31px under |

Every other `fit` call asks 581px or less.

## Scope

1. **The check.** `tools/client_checks/stage.py` and `tools/server_checks/stage.py` each
   wrap the staged `ui_kit.fit` once, at staging. Every call records the window's title
   and `winfo_reqheight()` and judges it on the spot: a window asking more than
   `768 - 80` is a `bad()` naming the window and the number, **unless** it has a direct
   child `tk.Canvas` holding a windowed `tk.Frame` - the one shape `ScrollRegion` builds
   and `pinned` already recognises. Judged at the call rather than in a group at the end,
   so `--group NAME` run alone still judges every window that group opens.
2. **The check cannot silently stop measuring.** One group per suite, `screen.py` in each
   check package, added to `GROUPS` in `tools/client-checks.py` and
   `tools/server-checks.py`, opens the five windows above and asserts the recorder saw
   each of them by title.
3. **The five windows over the line are wrapped in `ScrollRegion`**, footer pinned
   outside it, `size()` asked beside `fit` the way `gui_mail.py`'s `refit` does:
   `gui_proposals.py`, `gui_settings.py`, `gui_mail.py` (`mail_settings`),
   `server_gui.py` (`add_transaction`) and `notifier_remote.py` (`_open_with`).
4. **Remote Admin's two inner lists** (`notifier_remote.py`, the canvases around lines
   924 and 1743) bind `<MouseWheel>` on their own canvas. Once the window scrolls too,
   Tk delivers the event to the canvas and then to the toplevel, and both scroll. Their
   handlers return `"break"`, so the inner list takes the wheel alone.
5. Modify Transaction and Correct Transaction are under the line and are **not**
   wrapped. The check holds them: the day either crosses 688px, it fails.

## Not in this ticket

- `ScrollRegion` itself. It is used as it stands; converting `gui_users.py`'s inlined
  canvases to it is the refactor its docstring already declines.
- Shrinking a form to fit. `ScrollRegion`'s docstring rules that out.
- Width. Nothing measured is wider than 1366.

## Cascade

- `docs/reference/tooling.md` - the client and server check-group lists gain `screen`,
  and a sentence on the `fit` recorder beside each suite's staging description.
- `docs/reference/apps.md` - the five windows' bullets, where one states a size or says
  the window is fixed on both axes.
- `ui_kit.py` - `ScrollRegion`'s docstring says "Three windows"; the count is re-derived
  on the branch. `fit`'s docstring names both suites as holding the rule and stays true.
- No `APP_VERSION` bump here: no wire format, endpoint or stored file changes. It ships
  with the next feature bump.

**Left alone deliberately.** The earlier ticket files that measured these windows (017,
019-021) are the record of their moment.

## Verification

- Before the fix, on the branch: the new check fails on exactly the five windows in the
  table and on no other.
- After: `py -3.12 tools/gate.py --all` passes.
- By hand, both themes: each of the five, opened with the screen forced to 768, scrolls
  to its last field; the wheel scrolls the window; and on Remote Admin the wheel over an
  inner list scrolls the list only.

## Done when

Gate green, and a window added later that asks more than 688px fails the suite that
opens it.
