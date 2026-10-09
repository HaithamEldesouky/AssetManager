# 096 - The admin password is asked at the door only

**Type:** refactor · **Depends on:** none · **Issue:** [#278](https://github.com/HaithamEldesouky/AssetManager/issues/278)

## Finding

Backup / Restore is the shape: its `SECTIONS` entry in `server_gui.py` is gated
`"admin"`, so `_admin_again` asks for the admin password on every open, and
`gui_backup.py` carries no password field of its own. Every other console window
asks again inside, after the door has already been passed:

| Window | File | Door today | Asked inside |
|---|---|---|---|
| Lookup Sheet | `gui_assets.py` | `True` | top field, checked per action |
| Asset Sync | `gui_proposals.py` | `True` | top field |
| Asset Proposals | `gui_proposals.py` | `False` | top field |
| Capability Passwords | `gui_users.py` | `True` | top field, passed to `_set_capability_password` |
| Manage Users | `gui_users.py` | `True` | top field, passed to `_save_member`, `_rename_member`, `_delete_member`, `_set_member_password`; Storekeeper rename and toggles check it directly |
| Mail Settings | `gui_mail.py` | `True` | top field (the SMTP password beside it is not this) |
| Notification Rules | `gui_mail.py` | `True` | top field |
| Server Settings, Cut Over | `gui_settings.py` | `True` | dialog field, passed to `_cut_over_cert` |
| Add Transaction | `server_gui.py` | `False` | field in the form |
| Manage Transaction History, cancel a Confirmed one and the Storekeeper-cancel toggle | `gui_records.py` | `_console_unlock` in the pane | prompt, passed to `_cancel_transaction` |
| Clients: Send Command, the second command dialog, Clear Old Clients | `gui_clients.py` | none - the section is a pane | dialog field |
| System Log: Clear | `gui_log.py` | none - the section is a pane | dialog field |

## Scope

1. **Doors.** Every `SECTIONS` entry above that opens a window is gated `"admin"`
   (`_admin_again`, every open), including Asset Proposals and Add Transaction, which
   had no door. Import Transaction Archive and the Manage Transaction History pane keep
   `_console_unlock`. Display Settings stays ungated.
2. **Fields out.** Each window in the table loses its admin password field, its label,
   and the `_admin_password_ok` checks behind it. Error texts that name the admin
   password go with them.
3. **The register calls.** The console passes `authorised_as="Admin (Server GUI)"`
   where the function already takes it: `_save_member`, `_rename_member`,
   `_delete_member`, `_set_member_password`, `_cancel_transaction`.
   `_set_capability_password` (`server.py`) and `_cut_over_cert` (`server_cert.py`)
   gain `authorised_as=None` on the same terms: set, the password check is skipped
   and the value is the actor; the HTTP routes never pass it.
4. **Panes with no row.** Send Command, Clear Old Clients and Clear System Log ask
   `_admin_again` when the action is clicked, in place of their own field. Reached as
   `server_gui._admin_again`, not imported by name, so the staging patch in
   `tools/server_checks/stage.py` still reaches it.
5. **Change Admin Password keeps asking for the current password.** Rule 7.

## Not in this ticket

- The HTTP routes and their credentials: every `door(...)` line is unchanged.
- The Notifier's Remote Admin panels: they authenticate over the wire.
- `_console_unlock` itself.

## Cascade

- `docs/reference/apps.md` - each window's bullet where it says the window asks for
  the admin password inside.
- ADR-0015, ADR-0019 - re-read; amend only a sentence the change makes false.
- Docstrings in the touched `gui_*.py` that say "asked for once at the top".
- `tools/server_checks/*` - checks that type into the removed fields drive the door
  instead; the source scans in `capabilities.py` that look for `_console_unlock(`
  accept `"admin"` doors.
- No `APP_VERSION` bump, 095's reason: no wire format, endpoint or stored file
  changes. It ships with the next bump.

## Done when

`py -3.12 tools/gate.py --all` passes; no console window but Change Admin Password has
an admin password field; every entry that opens one asks at the door.
