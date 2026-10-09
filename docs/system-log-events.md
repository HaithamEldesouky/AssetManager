# System Log events

Every name this build can write to the System Log, what it means, and the level
it is written at. It is here because of **Notification Rules**: a rule is an
event name, the mailboxes it goes to and the least level that counts, and the
window offers only the names this server's log has *already seen* — so the
first time you want mail about `update.failed`, that event has by definition
never happened and is not in the list. Typing it is allowed and works. This is
the list to type from.

The window offering only what has happened is deliberate and is not a defect
(031): a catalogue kept beside the call sites would be the event list written
down twice, and it is the second copy that goes stale. What that costs is this
document, which is read by a person rather than by the server.

**The level is the half worth reading.** A rule's floor is the least level that
counts, so a rule at `warn` passes `warn` and `error` and leaves the ordinary
traffic alone. Setting a floor at `info` on an event sixty machines emit is a
mailbox nobody reads, which is the same as no rule at all.

**No `mail.*` event is ever notified.** A rule on one would mail about the mail
that could not be sent, fail again and log again; the hook skips them whatever
a rule says, so `mail.send_failed` is read in the System Log window and nowhere
else.

**Two bounds, and neither is silent.** At most one mail per event every
`_NOTIFY_MIN_SECS` (60) seconds, and `_NOTIFY_HOURLY_MAX` (60) in total per
hour across every rule — two rather than one because `POST /clients/log` is
unauthenticated, and either bound alone is walked around (one event a hundred
times defeats the ceiling, a hundred events once each defeats the per-event
limit). What a bound held back is **counted on the next mail that event does
send**, so a quiet hour and a bound holding all of it back are distinguishable.
The System Log itself holds every entry either way.

**The window says all of this in words as well** (#196). Every row in the
tables below has a phrase beside it in the Server GUI's System Log window,
under a **What happened** column sitting after Actor, so a row reads left to
right as who, then what they did, then the line of context. The `event` column
stays in front of it, because that short name is what a Notification Rule
matches on and what you type into the window this document exists for.

Those phrases are `EVENT_SENTENCES` in `server_log.py`, which is the same set
of names as the tables below and is **held equal to them in both directions**
by `tools/cascade-audit.py`: an event with no phrase is a window falling back to
the raw name, and a phrase for a row nobody documents any more is a phrase for
an event that has gone. So a new `_log_event` call adds a row here **and** a
phrase there, in the same commit. It is a second copy on purpose — nothing
under `docs\` ships in any package, so a table read out of this file at runtime
would be empty on every real install.

---

## Recommended floors

| what you want to be told about | rule | level |
|---|---|---|
| an update that did not work | `update.failed`, `update.rolled_back` | `warn` |
| a fleet taking a release | — | do not subscribe |
| somebody being refused | `auth.refused` | `warn` |
| a delegated credential being used | `remote.action` | `warn` |
| a restore | `restore.started`, `restore.finished` | `warn` |
| the register being replaced | `lookup.replaced` | `warn` |

**The update events are the sharpest case of the floor mattering.** Sixty
laptops taking one release produce up to sixty `update.applied` entries, and at
`info` that is one mail plus a held-back count saying nothing. The levels are
chosen so that a floor of **`warn`** mails exactly the failures:
`update.offered`, `update.declined`, `update.staged` and `update.applied` are
`info`; `update.download_failed` and `update.verify_refused` are `warn`; and
`update.failed` and `update.rolled_back` are `error`.

---

## Server

Written in process by `_log_event`, the one writer, with no source address
beside them — which is what makes a row claiming `component: Server` *with* an
address visibly a claim made over the network.

### Transactions

| event | level | what happened |
|---|---|---|
| `transaction.created` | `info` | A movement was recorded, through `_create_transaction`. |
| `transaction.confirmed` | `info` | The Engineer confirmed it. Carries `data` (#282): `{"origin": "desktop", "engineer": <the Engineer the Transaction names>}`, the Origin the server chose from the route. |
| `transaction.rejected` | `warn` | The Engineer denied the movement, with their reason. Carries `data` (#282): `{"origin": "desktop", "engineer": <the Engineer the Transaction names>}`. |
| `transaction.cancelled` | `warn` | Whoever recorded it says the movement never happened. |
| `transaction.modified` | `warn` | A Pending Transaction was corrected, naming which credential asked, and what changed: one line of `field: "old" -> "new"` per field that actually moved, the values cut to 60 characters each and the fields that did not fit counted rather than dropped in silence. Carries `data` (#246/071): `{"changes": [[field, old, new], ...], "dropped": n}`, the same fields and count `detail`'s line names, structured - which is what `_log_diff` reads for the correction popup instead of re-parsing that line, falling back to the parse only for a row this ticket predates. |
| `transaction.deleted` | `warn` | Rows were deleted. The rows are what stops existing, so this entry is the whole record of the act. |
| `transaction.auto_accepted` | `info` | The hourly job confirmed Transactions left Pending past 24h. Names a count, not an id. Carries `data` (#282): `{"origin": "auto", "engineers": [<each Engineer whose Transactions it confirmed>]}`. |
| `records.imported` | `warn` | A Transaction archive was restored, appending with new ids. |

### The Lookup Sheet and its assets

| event | level | what happened |
|---|---|---|
| `asset.saved` | `warn` | One asset was added or corrected, through `_save_asset`. |
| `asset.removed` | `warn` | One asset was removed. Transactions already recorded against it are untouched. |
| `lookup.replaced` | `warn` | Every asset was replaced from an uploaded workbook. |
| `lookup.imported` | `warn` | Assets were added from somebody else's file, saying how many were refused. |
| `assets.seeded` | `info` | A first run read the embedded workbook into the table. |
| `assets.ambiguous_identifier` | `warn` | Migration `010` cleared an identifier that named two assets, naming which. |
| `assets.duplicate_identifier` | `warn` | `init_db()` met the same state on a boot and started anyway. |

### Proposals

| event | level | what happened |
|---|---|---|
| `asset.proposed` | `warn` | A Storekeeper recorded an asset the register does not hold. |
| `asset.proposals_imported` | `warn` | A whole delivery was proposed as one file, one `proposed_at` for all of it. |
| `asset.proposal_approved` | `warn` | An Admin approved one, which writes the register. |
| `asset.proposal_rejected` | `warn` | An Admin refused one, with the reason the Storekeeper is shown. |

### Engineers, the Admin and the console

| event | level | what happened |
|---|---|---|
| `console.unlocked` | `info` | The admin password opened Server Administration. Every console act after it is `Admin (Server GUI)` with no password behind it, so **this is where the Admin proved who they were**. |
| `console.action_failed` | `error` | A Server GUI action raised instead of finishing - a config file the console account cannot write is the case it was written for. Nothing was saved and nothing was changed; the operator was shown the same sentence. |
| `auth.refused` | `warn` | A password was refused. |
| `admin.password_changed` | `warn` | The admin password was replaced. |
| `capability.password_set` | `warn` | A capability password and its holder were set. |
| `capability.password_cleared` | `warn` | One was cleared; the holder name goes with it. |
| `member.saved` | `info` | An Engineer was added or edited. |
| `member.deleted` | `warn` | An Engineer's row was removed. Their Own Password goes with it. |
| `member.renamed` | `warn` | An Engineer was renamed, naming the id and **both spellings** — which is what `_former_member_name` reads back. |
| `member.password_set` | `warn` | An Admin set an Own Password, which is Temporary. |
| `member.password_cleared` | `warn` | An Admin cleared one. |
| `member.password_changed` | `info` | The Engineer replaced their own. |
| `members.name_collision` | `warn` | `init_db()` met two names differing only in case and started anyway. |

### The network, remotely

| event | level | what happened |
|---|---|---|
| `remote.action` | `warn` | One of R1's endpoints was opened from somewhere else, carrying the capability, the holder and the source address — **written before the action runs**, so a call that then fails is still on the record. `POST /transactions/cancel` writes one for the capability password and not for the admin password (#169): there the admin password is the endpoint's own credential rather than a remote-channel one, and the `transaction.cancelled` beside it already records the act as the Admin's. |
| `remote.refused` | `warn` | One of them turned a credential away. |

### Certificates

| event | level | what happened |
|---|---|---|
| `cert.installed` | `warn` | A certificate was installed, naming the outgoing and the incoming fingerprints. Carries `data` (#246/071): `{"was": <outgoing fingerprint or "(none)">, "now": <incoming fingerprint or "(unreadable)">}`, and the phrase is a template over the two - `installed a certificate - was {was}, now {now}`. |
| `cert.removed` | `warn` | One was removed, naming what went. Carries `data`: `{"was": <fingerprint or "(none)">}`, and the phrase templates it - `removed the certificate - was {was}`. |
| `cert.exported` | `info` | The public half was written somewhere, naming the fingerprint. Nothing private travels. |
| `cert.generated` | `info` | A next certificate was staged. Nothing is bound and nothing is stranded. |
| `cert.pushed` | `warn` | `trust_cert` was queued for one Client, naming the staged fingerprint. |
| `cert.cutover` | `warn` | The staged pair became the live pair — written **before** anything moved, naming both fingerprints and how many installations are behind. Carries `data` (#246/071): `{"from": <live fingerprint or "(none)">, "to": <staged fingerprint>, "behind": n, "total": n}`, and the phrase templates all four. |
| `cert.cutover_failed` | `error` | It did not. |
| `cert.expiry_warning` | `warn` | The live certificate's `not_valid_after` is `CERT_WARN_DAYS` (30) or fewer days out. Written once a day from `_cert_expiry_loop` (#273) while it stays in that band; it only warns - staging and cutting over stay a deliberate act (ADR-0020). |
| `cert.expiry_critical` | `error` | The same reading, `CERT_ERROR_DAYS` (7) or fewer days out, in place of the warning rather than beside it. |

### Backup, restore and maintenance

| event | level | what happened |
|---|---|---|
| `backup.started` / `backup.finished` | `info` | A backup ran. |
| `backup.failed` | `error` | It did not. |
| `restore.started` / `restore.finished` | `warn` | A restore ran, naming the aside directory. `warn` on both, because a restore replaces the database. |
| `restore.refused` | `warn` | A backup was refused before a byte was written — a bad manifest, a newer schema, a name that is not a bare basename, or a digest that does not match. |
| `restore.failed` | `error` | It began and did not finish. |
| `maintenance.entered` | `warn` | Writes are being held for a backup or a restore. |
| `maintenance.left` | `info` | The hold came off. |
| `maintenance.left` | `warn` | The hold was **left behind by a process that is no longer running** and cleared at start. Same name, different level, on purpose: it is the same fact and only one of the two is worth being told about. |
| `write.held` | `warn` | A non-GET request was refused `503 maintenance`. |

### Mail and rules

**None of these is ever notified**, whatever a rule says.

| event | level | what happened |
|---|---|---|
| `mail.send_failed` | `warn` | The relay would not take a message. |
| `mail.test_sent` | `info` | Send test mail worked. |
| `mail.test_failed` | `warn` | It did not, in the mail server's own words. |
| `notify.rules_changed` | `warn` | The rules were saved. |

### The external asset system

| event | level | what happened |
|---|---|---|
| `sync.configured` | `warn` | The connection was saved. |
| `sync.started` | `info` | A run began, scheduled or from the console. |
| `sync.added` | `warn` | A run added an asset, or filled an empty field. |
| `sync.conflict` | `warn` | A run found a disagreement and **left it exactly as it was**. |
| `sync.finished` | `info` | It ended. |
| `sync.failed` | `error` | It did not, and nothing was written. |

### Clients, and the server itself

| event | level | what happened |
|---|---|---|
| `client.command_issued` | `warn` | A Command was queued for one Client. |
| `client.command_collected` | `info` | That Client took it, on a Check-in, exactly once. |
| `clients.cleared` | `warn` | Installations not heard from for longer than a chosen age were removed from the registry, naming the count, the threshold and how many are left. Written even where nothing matched when an Admin asked, at the console or over `POST /clients/clear` — the whole record those rows existed. The hourly auto-clear (#268) calls the same writer as `Auto-clear` but only where it actually removed a row, so an empty tick leaves no entry. |
| `server.started` / `server.stopped` | `info` | This process. |
| `server.config_changed` | `warn` | A setting in `server_config.json` was saved. Carries `data` (#246/071): the changed settings themselves, by name, plus a `"changed"` key naming which ones (the set varies call to call, so the phrase templates only that stable key) - `saved a server setting - changed {changed}`. |
| `server.port_moved` | `warn` | Under IIS, a new port was saved in Server Settings and the elevated half that moves the site binding was spawned (069, ADR-0021) — written **before** the spawn, an app pool restart being what follows it. Carries `data`: `{"from": <old port>, "to": <new port>, "site": <IIS site name>}`, and the phrase templates the two ports. At `warn` rather than `info` because the move ends by taking the old port away: a client switched off through the grace window needs its `config.json` corrected by hand. Written only where the port actually changed, and only under IIS — off IIS a saved port is `server.config_changed` and a restart. |
| `log.exported` | `info` | The System Log window wrote an `.xlsx`, saying how many rows and over what range. |
| `log.cleared` | `warn` | Rows were deleted — written **after** the delete, as the first row of the log that follows it, which is the only evidence it happened. |

---

## The two clients

Written locally by `common.log_event` into a rolling `client.log` and shipped to
the server on the tick, where they land through the same `_log_event` with the
source address the server saw beside whatever the client claimed. **A client
entry arrives over an unauthenticated channel** (ADR-0002, ADR-0005), which is
the whole reason the two notification bounds exist: a rule on one of these
names is a mail amplifier pointed at the department.

The Storekeeper attributes every entry to `<name> (Storekeeper)`; the Notifier
attributes to the Engineer it is configured as.

### Both clients

| event | level | what happened |
|---|---|---|
| `app.started` / `app.stopped` | `info` | This installation, naming its version. |
| `command.obeyed` | `info` (Storekeeper) / `warn` (Notifier) | A queued Command was carried out. **`update_now` (#177) words its own outcome and picks its own level**, being the one Command with three of them: the detail reads `update_now: applying <version>` at `warn` where the published release is being applied, `update_now: nothing newer than <version> is published` at `info` for the Client that was already there - which is an ordinary answer rather than a failure - and `update_now: <version> is published but this server holds no package for it` at `warn`, that last one being a case the queue refuses at issue time, so reaching it means the package stopped being there in between. What became of the update itself is the lifecycle below, not this entry. |
| `cert.trusted` | `warn` | A staged certificate was appended to the file this machine pins. Written only where one was **actually added**, so a reissued Command is not logged as a change. |
| `settings.opened_offline` | `warn` | Nothing answered, so the settings window opened with the Server URL alone and no password checked. **The Storekeeper's only since 090**: the Notifier's Settings has no password in front of it, so there is no unchecked opening to record. Kept for the Storekeeper and for a Notifier older than 090 still shipping it. |
| `settings.url_changed` | `warn` | That window saved a different Server URL. The Notifier writes it on every such save since 090, no password being asked there at all. |

### The update lifecycle — both clients

The first five are written by the app; the last three are written by
`common.report_update_result` on the **next start**, out of the
`update_result.json` the applier left, because phase two imports nothing of
ours and has no queue to put an entry in (#148).

| event | level | what happened |
|---|---|---|
| `update.offered` | `info` | A newer version is published and this installation was told. A launch check against a server that holds no package and no installer tells nobody and writes nothing — nothing was offered. |
| `update.declined` | `info` | Postponed, saying which of the five. |
| `update.download_failed` | `warn` | The package could not be fetched. Nothing was replaced. |
| `update.verify_refused` | `warn` | It was fetched and refused — the digest, the manifest, the Python version, or a name that escapes the install. Nothing was replaced. |
| `update.staged` | `info` | A verified package is staged and the app is restarting to apply it. **The last thing that process says.** |
| `update.applied` | `info` | The update worked, carrying both versions and the SHA-256 of the package. |
| `update.failed` | `error` | It never happened — the app was still running, or the applier itself failed. The old build is still installed. |
| `update.rolled_back` | `error` | It was applied and undone: the new build did not come up, or the extraction failed. |

**One gap, written down rather than papered over:** an update that rolls back
*and still fails to start the app* ships nothing, ever — there is no app left
to read the file. The evidence is `update.log` on that machine and that
installation going red in Connected Clients.

### Storekeeper only

| event | level | what happened |
|---|---|---|
| `transaction.submitted` | `info` | One Transaction reached the server, from the form or from Bulk submit alike. |
| `transaction.refused` | `warn` | The server turned one down. For a bulk row this is the only durable record it was attempted. |
| `transaction.buffered` | `warn` | The server could not be reached, so the movement is in `pending_buffer.json` waiting to be flushed. |
| `asset.proposed` | `warn` | An asset was proposed for an Admin to approve. |
| `asset.propose_refused` | `warn` | The server refused the proposal, in its own words. |
| `asset.propose_failed` | `warn` | It could not be asked at all. **A proposal is a question and is never queued.** |

### Notifier only

| event | level | what happened |
|---|---|---|
| `transaction.confirmed` | `info` | The engineer confirmed at this machine — written **whether or not the call got through**, because what this file answers is what the engineer did here. |
| `transaction.rejected` | `warn` | The engineer rejected, with the reason. Same rule. |
| `transaction.dismissed` | `info` | The engineer put the popup away on purpose (#201). Nothing is confirmed, nothing is rejected and nothing is sent — the Transaction goes back to the front of the queue and is offered again on the popup's own return interval, so this entry is the only record that it was in front of somebody and was deferred. |
| `answer.buffered` | `warn` | The server would not take that answer yet, so it is in `pending_answers.json` for the next tick. |
| `answer.refused` | `warn` | It was refused permanently and has left the queue. Nothing is shown — the engineer answered that Transaction long ago. |
| `member.renamed` | `warn` | This installation adopted a new spelling of its Engineer's name off the Check-in. |
| `user.logged_off` | `info` | The engineer chose Log off on the tray (090). The name is cleared and the logon window opens; the next entry from this machine is under whoever logs on. |

---

## Adding an event

Write the `_log_event` or `log_event` call, pick the level against what a
subscriber would want (`info` for a thing that happened, `warn` for a refusal
or something an Admin has to act on, `error` for something that did not work at
all), and **add the row here in the same commit** — this file is the only place
the set is written down for a person, and a name missing from it is a rule
nobody can write until the event has happened at least once.
