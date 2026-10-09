# Asset Manager — Project Context

Internal IT asset tracking for the IT department. Four Python apps over one SQLite
database, deployed across an internal Windows domain: source payloads plus one
PyInstaller installer.

---

## The files

| File | What it is |
|------|------------|
| `server.py` | The **Asset Server** — Flask REST API, SQLite, background jobs. One program, three modes: Windows Service, headless `serve` behind IIS, interactive GUI. |
| `server_gui.py` | The Server GUI — the Tkinter console interactive mode opens (#207). Imported by `server.py` through the `bind()` pattern `server_cert.py` set: `S.<name>` reaches back for what stays in `server.py`. |
| `server_cert.py` | The server's certificate lifecycle — stage, push, cut over, export (ADR-0020). Imported by `server.py`; called from its routes and from `server_gui.py`'s console. |
| `register_assets.py` | The Assets register — the four functions that read and write the `assets` table (#215). Imported by `server.py`, which hands it `get_db` and `_log_event` through `bind()`; called from its lookup routes and from `server_gui.py`'s asset windows. |
| `register_transactions.py` | The Transactions register — the four functions that read and write the `transactions` table (#216): create, cancel, modify, and what is still pending. Imported by `server.py`, which hands it `get_db` and twelve more names through `bind()`; it imports `register_assets` for `_asset_key_sql` rather than re-deriving which asset a row names. |
| `register_engineers.py` | The Engineers register — the six functions that read and write the `team_members` table (#217): one Engineer by name, one by id, the whole list, and the save, delete and rename. Imported by `server.py`, which hands it `get_db` and nine more names through `bind()`; `_KEEP` travels the other way, defined beside the `_save_member` signature that defaults to it and imported back. |
| `server_mail.py` | Mail, and which events are mailed (#224) - the SMTP settings, the one stored password, the send that never waits, and the rules that decide which System Log entry reaches a mailbox. Imported by `server.py`, which hands it `_log_event`, `_secret_set`, `_secret_get` and five more names through `bind()`; `_KEEP` it imports from `register_engineers` itself, a default argument being evaluated before any `bind()` runs. |
| `server_sync.py` | The external asset system (#225) - the one-directional read of another system's asset list and the reconcile that folds it into the Assets register, never deleting and never overwriting a field already filled in (ADR-0014). Imported by `server.py`, which hands it `get_db`, `_load_assets`, `_save_asset`, the `_secret_set`/`_secret_get` pair and ten more through `bind()`; no route reaches it, `server_gui.py`'s Asset Sync window calls all of it and `_start_background_jobs` starts `_sync_loop`. `_sync_admin_cfg` shares the prefix and nothing else, and stayed. |
| `server_clients.py` | The registry of installations (#226) - what every Client machine says about itself and what may be said back to it: the check-in, the command vocabulary and the queue behind it, the registry as the console reads it, and the stale sweep. Imported by `server.py`, which hands it `get_db`, `_log_event`, `_client_package`, `_since_ts` and three more through `bind()`; the five `/clients*` routes stayed in `server.py` and call in, `server_gui.py`'s Connected Clients window reaches it as `S.<name>`, and `server_cert.bind()` is handed four of its readers. |
| `server_log.py` | The System Log (#227) - the one writer every act in this build passes through, the words a row reads as (`EVENT_SENTENCES`), the readers the console's System Log window draws with, the clear behind its button, the batch a Client ships, and the two retention bounds with the hourly job that applies them. Imported by `server.py`, which hands it `get_db`, `_notify_of` and `db_path` through `bind()` **above** the block that binds the other five, every one of those calls being handed `_log_event`; `POST /clients/log` stayed in `server.py` and calls `_record_log` in, and `server_gui.py`'s System Log window reaches the readers as `S.<name>`. |
| `server_archive.py` | Backup, restore, the schema migrations and the archive (#228) - a copy of this install and putting one back (ADR-0019), the migration engine `tools/*.ps1` drive through `AssetServer.exe migrate`, and the record archive the console exports and imports. Imported by `server.py`, which hands it `get_db`, `_maintenance`, `db_path` and nine more through `bind()`; no route moved - `POST /records/import` stayed in `server.py` and calls `_import_records_xlsx` in - and `server_gui.py`'s Backup and Restore window and its Manage Records reach it as `S.<name>`. The three `os.path.join(BASE_DIR, ...)` constants the block defined stayed too, so `tools/cascade-audit.py`'s `BESIDE_MODULES` scan still sees them. |
| `server_lookup.py` | The asset lookup's write path, and the proposals (#229) - the embedded sheet a first run writes, the workbook both directions of the interchange format use, the column mapping and the row verdicts an import is decided by, the proposals a Client raises and the Admin answers (ADR-0017), and the three readers every caller asks what the sheet says. Imported by `server.py`, which hands it `DEFAULT_LOOKUP_B64`, `ASSET_TYPES`, `LOOKUP_PATH`, `get_db` and `_log_event` through `bind()`; the nine `/lookup*`, `/asset*` routes stayed in `server.py` and call in, `server_gui.py`'s Manage Assets and Asset Proposals windows reach it as `S.<name>`, and `register_transactions.bind()` and `server_sync.bind()` are each handed some of its functions. It imports `register_assets` for `_save_asset`, `_load_assets` and `_IDENTIFIER_TAKEN` rather than being handed them - three reads into the register and none into `register_transactions`, which is what makes it a module beside them rather than a second interface onto them. |
| `server_iis.py` | Is there an IIS in front of this process, and what has it bound (#243) - `_iis_host`, `_port_serves_tls` and `_iis_tls_bound` out of `server.py`, `_bind_cert_command` out of `server_cert.py`, and `server.py`'s own `_remote_tls_ok` beside them: one concern under two names in two files. Imported by `server.py`, which hands it `BASE_DIR`, `PORT` and `IIS_STATE_PATH` through `bind()`; no route moved with it, `server_gui.py`'s console reaches `_iis_host` and `_iis_tls_bound` as `S.<name>`, and `server_cert.py` imports `_bind_cert_command` back rather than defining it. |
| `gui_*.py` | The console's twelve windows, nine modules (#235) - `gui_proposals.py` (Asset Proposals, Asset Sync), `gui_assets.py` (Manage Assets), `gui_users.py` (Capability Passwords, Manage Users), `gui_clients.py` (Connected Clients), `gui_log.py` (System Log), `gui_backup.py` (Backup and Restore), `gui_mail.py` (Mail Settings, Notification Rules), `gui_records.py` (Manage Records) and `gui_settings.py` (Server Settings). Imported by `server_gui.py` below its `THEME`, which re-exports the twelve names so `run_gui` and `server.py` call them as they always did; none of them calls `bind()` - each writes `from server_gui import S` inside the window, and keeps a `_bind_palette()` seeded off `server_gui.THEME`. |
| `storekeeper_app.py` | The Storekeeper's client. Logs movements in and out of the store - the form, the history and the offline buffer; its Export, Bulk submit and Propose/Import windows are the three rows below. |
| `storekeeper_export.py` | The Storekeeper's export, beside its window (#219) — the dialog that picks a date range and the workbook it writes. Imported by `storekeeper_app.py` through the `bind()` pattern `server_cert.py` set: it reaches back for the palette and imports the rest itself. |
| `storekeeper_bulk.py` | The Storekeeper's Bulk submit window (#236) - one engineer, one direction, many assets, and the queue behind them. `class BulkWindow` takes the app itself and reads its seven attributes live as `self.app.<name>`; `bind()` hands it the palette and `S._sk_name`/`S.sk_actor`, `storekeeper_export.py`'s shape. |
| `storekeeper_propose.py` | The Storekeeper's Propose and Import dialogs (#237) - an asset the lookup sheet does not hold, proposed one at a time or from a file. `class ProposeDialogs` takes the app itself and reads its five attributes live as `self.app.<name>`; `bind()` hands it the palette and `S.sk_actor`/`S.save_config`, `storekeeper_bulk.py`'s shape. |
| `notifier_app.py` | Each engineer's tray client. Confirms or rejects what was logged against them — the tray, the popup, the Dashboard and the forms behind them. |
| `notifier_pending.py` | The Notifier's Pending decisions, below the window (#208) — a Confirm or a Reject, the offline hold, and the order the popup queue is drained in. No tkinter and no transport: it returns what should happen and `notifier_app.py` performs it. |
| `notifier_remote.py` | The Notifier's Remote Admin surface, below the tray menu (#218) — the console an engineer opens on their own machine, the probe that learns what a capability password opens, and the seven panels behind it. Imported by `notifier_app.py` through the `bind()` pattern `server_cert.py` set and `server_gui.py` repeated: `N.<name>` reaches back for what stays in `notifier_app.py`. |
| `installer.py` | Builds `AssetManager_Setup.exe` — the one binary we ship (rule 12). |
| `common.py` | The wire layer the three clients share (rule 10). The server never imports it. |
| `ui_kit.py` | The palette, widgets and sizing every window shares, and the app icon every one of them carries. The depth layer stood beside it in `ui_glass.py` from #222 until 074 deleted it (ADR-0022); the icon came back here with the deletion, and is pillow's one reader left. |
| `client_update.py` | Applies the next release in place, in two phases. |
| `applaunch.py` + the four `run_*` launchers | Source mode — what Windows actually starts (rule 14). |

Every row in full, and why the component is called the Asset Server while its
identifiers are not: [docs/reference/architecture.md](docs/reference/architecture.md).

---

## Infrastructure (hardcoded — do not change)

- **Host** `asset-server`, **IP** `192.0.2.100`, **port** `8081`. The port is editable
  from the Server GUI or `POST /admin/server_config`; a change needs a restart, and
  online clients pick it up themselves through `resolve_server_url`.
- **Protocol** HTTP, or HTTPS with a self-signed certificate. Never `verify=False`.
  Default server URL `https://asset-server:8081`.
- **Database** SQLite `assets.db`, beside the server unless `db_path` in
  `server_config.json` moves it: absolute local paths only, setting it does not move the
  file, and a configured path with nothing at it stops startup rather than starting empty
  (ADR-0004).
- **Admin password** salted PBKDF2-HMAC-SHA256 in `admin_config.json` (ADR-0008). Set at
  install, changed only from the Server GUI, and the credential that opens the console.

---

## Team

- **Storekeeper:** Storekeeper User (only user of StorekeeperApp)
- **Engineers (each runs Notifier):**
  - Alice Carter
  - Brian Dawson
  - Carol Evans
  - David Foster

`TEAM_MEMBERS` is the fallback shown when the server cannot be reached; the live
list comes from `GET /members`. The three clients share one copy in `common.py`.
`server.py` keeps its own seed list and does not import `common.py` (rule 10).

---

## Strict Project Rules — Never Break These

Fourteen, and none of them bends. Each one below is the rule; the reasoning that put it
there, and the failure it is standing in front of, is in
[docs/reference/rules.md](docs/reference/rules.md). Read that before you argue with one.

1. **HTTP or HTTPS on port 8081.** Never `verify=False`. The clients fail closed: with no
   `ssl_cert.pem` beside the app, an `https://` request raises rather than connecting.
2. **Asset types are driven by the lookup sheet.** `GET /asset_types` serves the distinct
   `asset_type` values of the `assets` table; clients read it through
   `common.fetch_asset_types()`, which keeps an on-disk cache.
3. **No "Asset Name" field anywhere.** Asset No. and Serial No. are the only identifiers.
4. **Asset Number and Serial Number come first** — first fields in every form, first data
   columns in every table.
5. **At least one of Asset Number or Serial Number is required** to submit a transaction.
6. **Submit validates against the lookup sheet, on the server**, and every creation goes
   through one function, `_create_transaction`. Neither identifier found is a 400 with
   `code: "not_in_lookup"`; found, and type and both identifiers are corrected to the
   sheet's canonical values.
7. **The admin password is changed only from the Server GUI, and is never delegable.** No
   client sets a password of any kind. An engineer's own password is a separate thing, set
   from the Server GUI's Manage Users window.
8. **Permission names live in one place, and that place is `server.py`** — `PERMISSIONS`,
   with `PERMISSION_LABELS` beside it as captions, not a second list. No client carries a
   copy.
9. **There is NO `/reset` endpoint.** There is a Clear All Records button in the Server
   GUI, behind the admin password and a confirmation.
10. **Shared client code lives in `common.py`.** Add to it, never re-copy. The server
    stays out of it and shares no transport code with the clients.
11. **`asset_lookup.xlsx` is embedded** in `server.py` as `DEFAULT_LOOKUP_B64`; since 024
    the assets live in the `assets` table and the workbook is the interchange format
    (ADR-0011). Two doors update it, both admin-password only.
12. **We ship one executable of ours and it is the installer.** The three app exes were
    retired by 061; what Windows starts now is a signed `python.exe`/`pythonw.exe` with
    one of our launchers as its argument.
13. **The vendored `lib\` is tied to one Python minor version.** `vendor.ps1` stamps
    `lib\PYVER` and `applaunch.py` refuses to start on a mismatch, naming the version to
    install. Never drop that check.
14. **Source mode is the only mode, and the engineer-laptop proof is the gate on it.** Do
    not release a build from here until a source-mode client has been installed and run on
    a real engineer laptop — there is no exe path left to fall back to.

---

## Cascade

- **Stay inside the blast radius.** Touch only the file(s) the fix requires. The four apps
  share a wire format, so never rename a JSON field or DB column without a stated
  migration plan: clients update independently and an older one must keep working
  mid-rollout.
- **Cascade a change to everything that records the same fact.** The blast radius rule
  above is about *code*: don't touch code the fix doesn't need. This rule is the other
  half — a fact that is written down in more than one place must move in all of them in
  the same commit, or the copies start lying. Leaving a stale copy is not "staying in
  scope", it is shipping a contradiction. The coupled sets in this repo, all of which have
  bitten:

| change this | and these must move with it |
|---|---|
| `APP_VERSION` | all four sources - `package.ps1` refuses a package when they disagree |
| `PASSWORD_MIN` | `server.py` **and** the copy `installer.py` keeps |
| a permission name | `PERMISSIONS` **and** `PERMISSION_LABELS` in `server.py`, and the count `CONTEXT.md` states in words |
| the engineer list | `TEAM_MEMBERS` in `common.py` **and** `server.py`'s own seed list |
| a DB column | the migration, `init_db()`'s idempotent `ALTER TABLE`, and the schema block in `docs/reference/database.md` |
| an endpoint's shape | the API table in `docs/reference/api.md` **and** every client that calls it |
| a route's credential | its `door(...)` line in `server.py` **and** the Credential column in `docs/reference/api.md` |
| a `tools/*.ps1` behaviour | that script's section in `docs/reference/tooling.md` **and** the runbook that drives it |
| a capability name or label | `CAPABILITIES`, `CAPABILITY_LABELS` and `CAPABILITY_REMOTE` in `server.py`, the Capability Passwords bullet in `docs/reference/apps.md`, ADR-0006 and ADR-0015 |
| a new domain term | the glossary in `CONTEXT.md` - its wording, not a synonym it warns off |
| the Storekeeper's role label | `"%s (Storekeeper)"` in `server.py` **and** in `storekeeper_app.py` |
| the Storekeeper's default name | `STOREKEEPER_DEFAULT` and the `transactions.storekeeper` column default in `server.py`, `DEFAULT_CFG` in `storekeeper_app.py`, and the Notifier popup's fallback |
| a client module, shared or one app's | `$Payload` or that app's `$Apps.<key>.Extra` in `tools/bundle-client.ps1`, **and** `SOURCE_FILES` in `installer.py` |
| a shipped payload | rebuild the affected packages, and re-stamp at release time - a docs-only commit does not invalidate one |
| a documented measurement or claim | re-derive it from the source; never copy it forward from notes or an earlier draft |
| a new module beside an app | the four lists nothing derives and no gate holds - `MAP` in `tools/gate.py`, the two staging lists in `tools/server_checks/stage.py`, and `tools/client_checks/stage.py`'s staging block with the `SRC_FILES` tuple beside it. `$SourceFiles`, `dev-run.ps1`'s staged lists and `$Payload`/`SOURCE_FILES` are gate-held and are not this row |
| a `_log_event` call | its row in `docs/system-log-events.md` **and** its phrase in `EVENT_SENTENCES` in `server_log.py` |

When a change lands in a doc that another doc points at, follow the pointer and check
the sentence on the other side still holds. Say what you cascaded; if you deliberately
left a copy alone, say which and why.

Every row above is one line because two tickets that cascade into one long line cannot
merge. What each row cost when it drifted is in
[docs/reference/cascade.md](docs/reference/cascade.md).

---

## Before you call a change done

- `ast.parse()` every Python file you edited.
- Hit any endpoint you changed against a running server and check what comes back.
- `py -3.12 tools/gate.py` — the gates your diff can actually reach, run in parallel.
  It always runs `tools/cascade-audit.py`, the gate on most of the table above: that one
  reads this file and every document under `docs/`, so a fact moved in code and not in
  prose fails here rather than in production. A path `gate.py` does not recognise runs
  every gate rather than none. `--all` is the release run, and what `land.py` does.

---

## Where the rest lives

| Reach for | When |
|-----------|------|
| [docs/reference/rules.md](docs/reference/rules.md) | a rule above is in your way, or you need what it is standing in front of |
| [docs/reference/architecture.md](docs/reference/architecture.md) | changing what an app *is* — its modes, entry points, or the shared kit |
| [docs/reference/database.md](docs/reference/database.md) | adding a column, writing a migration, reading the schema |
| [docs/reference/api.md](docs/reference/api.md) | adding, changing or removing an endpoint |
| [docs/reference/apps.md](docs/reference/apps.md) | changing a window, a dialog, or a client behaviour |
| [docs/reference/tooling.md](docs/reference/tooling.md) | changing anything under `tools/` |
| [docs/reference/files-on-disk.md](docs/reference/files-on-disk.md) | adding a file an app writes beside itself |
| [docs/runbooks/release.md](docs/runbooks/release.md) | packaging a build or pushing an update |
| [docs/runbooks/iis-cutover.md](docs/runbooks/iis-cutover.md) | putting the server behind IIS |
| [docs/runbooks/source-mode.md](docs/runbooks/source-mode.md) | installing a client without the setup exe |
| [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md) | before writing code |
| [CONTEXT.md](CONTEXT.md) | naming anything — the glossary is the house wording, and a synonym it warns off is wrong |
| [docs/adr/](docs/adr/) | the decision is already settled; twenty-five of them |
| [docs/system-log-events.md](docs/system-log-events.md) | adding or reading a System Log event |

---

## Agent skills

Per-repo configuration for the engineering skills.

- **Issue tracker** — GitHub issues, driven with the `gh` CLI. See
  [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).
- **Triage labels** — five canonical roles, used verbatim as label strings. See
  [docs/agents/triage-labels.md](docs/agents/triage-labels.md).
- **Domain docs** — single-context: `CONTEXT.md` plus `docs/adr/`. See
  [docs/agents/domain.md](docs/agents/domain.md).
- **Prototype** — capture visuals with a headless browser; do not take screenshots.
- **Ticket workflow** — one ticket per feature, bug fix or refactor; a ticket whose
  dependencies are not closed and merged is refused; a ticket lands as one squash commit,
  so `git log main` is the list of tickets; two tickets that cascade into the same line of
  this file are sequenced, not started together. See
  [docs/agents/ticket-workflow.md](docs/agents/ticket-workflow.md).
- **Pull requests** — **this repo overrides the global rules.** Merge `main` in and push,
  then stop. No pull request is opened, proposed or asked about, and no code review runs,
  unless either is asked for directly. Landing is a separate step: close the ticket, merge
  to local `main`, push `main`, delete the branch. See
  [docs/agents/pull-requests.md](docs/agents/pull-requests.md).
