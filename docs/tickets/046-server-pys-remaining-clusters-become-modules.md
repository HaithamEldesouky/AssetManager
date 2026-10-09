# 046 - server.py's remaining clusters become modules

**Type:** plan · **Depends on:** 043 · **Found by:** architecture review, Sep 2026 · **Issue:** [#220](https://github.com/HaithamEldesouky/AssetManager/issues/220)

## Finding

Once 041-043 land, `server.py` has given up the GUI (036), the certificate lifecycle
(035) and the Assets/Transactions/Engineers registers (041-043). What is left is not one
concern - it is six, each already a contiguous or near-contiguous block with its own
naming convention, verified against the current tree (10,545 lines):

| cluster | span | lines | what's there |
|---|---|---|---|
| sync | `2659` (isolated); `8955-9451` | 1 + 497 | `_sync_admin_cfg` alone near the top; `_sync_secret_*` through `_sync_loop` as one block, ending before the `lookup_asset` route at 9452 |
| mail and notification rules | `8459-8954` | 496 | `_smtp_*`, `_send_mail*`, `_notify_rules`/`_save_notify_rules`/`_notify_gate`/`_notify_of`, ending before the sync block |
| clients and commands | `7217-8059` | 843 | `_record_checkin` through the client/command routes around `COMMANDS` (`7354`) and `_clear_stale_clients` (`7590`), ending before the system log cluster |
| system log | `8060-8458` | 399 | `event_phrase` through `_log_retention_loop`, ending before the mail cluster |
| lookup import and proposals | `4313`, `4744`, `4912`, `5196` (scattered) | - | `_import_records_xlsx`, `_validate_import_rows`, `_load_proposals`, `_load_lookup_table` - interleaved with the Assets cluster 041 already moved out from around them, not contiguous |
| backup/restore | `3801-4255` | 455 | migration helpers, `_backup_members`/`_take_backup`/`_verify_backup`/`_restore_*`, `_export_records_xlsx`/`_export_log_xlsx`, ending before the lookup-import cluster |

One ticket per cluster is the rule `docs/agents/ticket-workflow.md` "Splitting" states -
"never a ticket that is two of those" - so this ticket files no code. It exists to record
the spans above against the tree as it stood once 043 landed, since every earlier ticket
in this chain (035, 036, 039, and the split into 041-043) shows line numbers drift the
moment the ticket ahead of them lands. A ticket for sync, mail, clients, system log,
lookup/proposals or backup/restore that copies the table above without re-deriving it by
grep is copying a number from an older ticket, the exact failure this repo's own process
warns against.

**Lookup import and proposals is not a clean move.** `_import_records_xlsx` was already
named in 039's finding as the second writer into `transactions` that rule 6 does not yet
enforce - out of scope there and out of scope here too. Whoever files that cluster's ticket
should expect it to touch `register_assets.py` (041) and possibly `register_transactions.py`
(042) rather than standing alone the way the other five do; say so in that ticket's own
Depends-on line once written, do not assume it is independent because this table lists it
last.

## Scope

None. This ticket names the six clusters, their approximate spans and what forces each
into its own ticket rather than one big one; it files no module and moves no line.

Each cluster above is filed as its own ticket - `047` onward for this half of the chain, or
whatever numbers are open when they are written - once 041, 042 and 043 have landed and the
table above has been re-measured against the tree they leave behind. The order among the
six is not fixed here: sync, mail/notify and clients/commands touch no table 041-043
moved and may be filed and sequenced in any order relative to each other; system log and
backup/restore read across several tables and should be read again once the others have
landed, in case a cluster they log or back up has itself moved.

## Not in this ticket

- Any actual move. That is each cluster's own ticket, filed later.
- Re-deriving the table above before 041-043 have merged. The spans here are a snapshot of
  the current tree and are expected to be wrong by the time they matter - that is stated,
  not a defect.
- `tools/server-checks.py`'s own split. That is 047, independent of this ticket's six
  clusters and depends on 043 directly rather than through this one.

## Cascade

None - a plan ticket moves nothing. Each cluster's own ticket, once written, owes the same
shape of cascade 035/036/041-045 all do: `CLAUDE.md`'s files table,
`docs/reference/architecture.md`, `docs/CODING_STANDARDS.md` "Where code goes",
`tools/package.ps1:148` `$SourceFiles`, `tools/server-checks.py`'s staging tuple
(`tools/server-checks.py:141`, already carrying four names and about to carry three more
from 041-043), and `tools/gate.py`'s `MAP`. State the real line numbers when each cluster's
ticket is written; this ticket's table is a starting point for that grep, not a citation
for it.

## Verification

None - nothing here is built. The verification that matters is each cluster's own ticket
re-deriving its span by grep against the tree at the time it is written, rather than
trusting this table.
