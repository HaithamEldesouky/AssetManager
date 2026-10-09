# Tickets

Tickets live here as files - one file per ticket, the same split
`docs/agents/ticket-workflow.md` describes - **and** as GitHub issues on `origin`
(`HaithamEldesouky/AssetManager`), which is the live tracker and is numbered past #205.

**The numbering here is local to this directory and is not the issue number.** A ticket
filed on both carries its issue number in its own metadata line, and in the table below.
The file is authoritative for Scope, Cascade and Verification; the issue is the tracker
entry that points at it.

001-018 are merged. 019 is filed and not started.

| Ticket | Subject | Depends on |
|---|---|---|
| 001 | `package.ps1` generates a self-signed certificate | - |
| 002 | Storekeeper: Asset Type auto-populated, not picked | - |
| 003 | Storekeeper: Appearance moves to the header as a sun/moon toggle | - |
| 004 | Server GUI: Add Transaction gets the lookup auto-resolve | - |
| 005 | Server GUI: manage the asset lookup from the Database card | - |
| 006 | All apps: controls reflow when the window is resized | 002, 003, 004, 005 |
| 007 | Bug: Notifier popup survives a confirm/reject from the Dashboard | - |
| 008 | `client-checks.py` covers the popup dismissal 007 fixed | 007 (done) |
| 009 | Server GUI: a Manage Users window (Engineers, Admin, Storekeeper) | - |
| 010 | Server GUI: the admin manages RBAC profiles; sensitive actions become permissions | 009 |
| 011 | A system log across all three components | - (run after 009) |
| 012 | Notifier: an Own Password opens Settings; the URL changes offline | 010 |
| 013 | Storekeeper: creating an Engineer only, no password and no permissions | 009, 010 |
| 014 | Storekeeper: the Server URL changes while offline | 012 |
| 015 | Bug: the admin password is refused in the current-password field | - |
| 016 | Bug: with `view_all_history` the Pending queue offers another Engineer's rows | - |
| 017 | Bug: Manage Users asks 1423px of height and loses its bottom control | - |
| 018 | The `/clients` invariant needs narrowing; System Log window unmeasured | - |
| 019 | A window resizable on both axes is judged at its own minimum | 018 |
| 020 | Bug: Connected Clients loses its whole footer at its own minimum | 019 |
| 021 | The Lookup Sheet window is unmeasured, and 019 never noticed | 019 |
| 022 | package.ps1 absorbs the build, and stops making two copies of everything | - |
| 023 | Asset Server in the words, not in the identifiers | - |
| 034 | An Engineer's name matches without regard to case | 023 (lands before 024) |
| 024 | Assets move into the database; the sheet becomes an import/export format | 023 |
| 025 | Asset uniqueness is enforced at the store, not at one window | 024 |
| 026 | Asset Model is picked from the models that exist | 024 |
| 027 | Import assets from xlsx or CSV, with the columns mapped by hand | 024, 025 |
| 028 | The Storekeeper proposes an asset; the Admin approves it | 024, 025 |
| 029 | A Storekeeper's proposal can arrive as a file | 027, 028 |
| 030 | The Asset Server can send mail | 023 |
| 031 | Which events are mailed, and to whom | 030 |
| 032 | An external asset system syncs into the register | 024, 025, 027, 031 |
| 033 | The exe and the service take the new name | 023 (runs last) |
| 035 | The certificate lifecycle becomes a module of its own (#206) | - |
| 036 | The Server GUI lifts out of `server.py` (#207) | 035 |
| 037 | The Notifier decides below the window (#208) | - (sequence behind 036) |
| 038 | One enforcement point for the password check (#209) | 036 |
| 039 | The Register gets an interface (#210) — superseded by 041-043 | 036, 038 |
| 040 | The last duplicated client helpers move into `common.py` (#211) | - |
| 041 | The Assets register gets an interface (#215) | 036, 038 |
| 042 | The Transactions register gets an interface (#216) | 041 |
| 043 | The Engineers register gets an interface (#217) | 041 |
| 044 | The Remote Admin surface lifts out of `notifier_app.py` (#218) | 037 |
| 045 | The Storekeeper's export lifts out (#219) | 044 (cascade lines only) |
| 046 | `server.py`'s remaining clusters become modules — a plan ticket, files no code (#220) | 043 |
| 047 | `tools/server-checks.py` splits by check group (#221) | 043 |
| 048 | `ui_kit.py`'s glass rendering lifts out (#222) | - (sequence after 044, 045) |
| 049 | The instructions stop describing the apps as flat single files (#213) | 035, 036, 037, 038, 040, 041, 042, 043, 044, 045, 046, 047, 048, 050, 051, 052, 053, 054, 055 |
| 050 | Mail and the notification rules become a module (#224) | 043 |
| 051 | The external asset sync becomes a module (#225) | 050 (cascade lines only) |
| 052 | The client registry and its commands become a module (#226) | 051 (cascade lines only) |
| 053 | The System Log becomes a module (#227) | 052 |
| 054 | Backup, restore and the archive become a module (#228) | 053, and 042 |
| 055 | The lookup import and the proposals become a module (#229) | 054, 041, 042 |
| 056 | `SHIPS` names no register module, and a package manifest goes stale unreported (#230) | 055 (cascade line only) |
| 057 | The imports each lifted module left behind (#231) | 055 |
| 058 | The imports the client lifts left behind (#232) | 057 |
| 059 | Nothing holds `$SourceFiles` to what the server actually imports (#233) | 056 |
| 060 | `server_gui.py` splits one window per module (#235) | - (sequence after the 2.6.0 release) |
| 061 | The Storekeeper's bulk window lifts out (#236) | - (sequence after the 2.6.0 release) |
| 062 | The Storekeeper's propose and import dialogs lift out (#237) | 061 (sequence after the 2.6.0 release) |
| 063 | `tools/client-checks.py` splits by check group (#238) | - (sequence after the 2.6.0 release) |
| 064 | The narrow-band leg settled on two identical reads (#239) | - (closed, merged) |
| 065 | The console's Lookup Sheet menu: Proposals and Sync reached from one door (#240) | - (lands before 060) |
| 066 | Connected Clients on the action row; Database Location behind the console door (#241) | 065 |
| 067 | A forwarded client address is a refusal, a check and a hint, not a warning (#242) | - |
| 068 | What the server knows about the IIS in front of it becomes a module (#243) | - |
| 069 | Changing the port moves the IIS binding (#244) | 068 |
| 070 | Installing or removing a certificate under IIS moves the binding, or refuses (#245) | 068 |
| 071 | A System Log entry carries structured data, and its sentence reads it (#246) | - |
| 072 | The clients ship structured data with each entry (#247) | 071 |
| 073 | The flat palette, and the contrast gate that holds it (#248) | - |
| 074 | `ui_glass.py` is removed, and the render with it (#249) | 073 |
| 095 | Every window taller than the screen scrolls (#270) | 091, 093 |
| 096 | The admin password is asked at the door only (#278) | - |
| 103 | An asset has a numeric Asset Number, a Serial Number and a Type (#279) | - |
| 104 | Bug: the console reads an IIS HTTPS server as it is (#280) | - |
| 105 | A Client reports its own address (#281) | - |
| 106 | A decided Transaction records its Origin (#282) | - |
| 107 | The Origin label is shown where a decision is read (#283) | 106 |
| 108 | A popup answered elsewhere closes and says so (#284) | 106, 107 |

023, 034, 024, 025, 026, 027, 028, 029, 030, 031 and 032 are done, in that order. 033 is filed and unscheduled. 032 was filed as blocked on the external system's facts; it was built against a stubbed transport instead, since what the facts decide is a base URL, a path and a field mapping - all four of them settings an Admin types into the window (ADR-0014) rather than anything the code has to know first. They are one chain and are merged in the order the table lists them, dependency first (`../agents/ticket-workflow.md`): 023 lands alone and first because every ticket behind it rewrites the same `CLAUDE.md` lines, 034 goes in second for the same reason against the schema block, and 033 is a cutover that runs last.

035-055 come out of an architecture review (Sep 2026). 035, 036, 040 and 211 are merged. They are a refactor chain, not features: 035 and 036 split `server.py` - 18,703 lines in one scope, at the time - into an API and a console, and 038 and 039 were meant to deepen what is left. **035 and 036 both edit `$SourceFiles` at `tools/package.ps1:147`, one line, so they were sequenced rather than started together**; 037 and 040 touch only the clients and are independent of the chain, but both cascade into the long `common.py` and `ui_kit.py` rows of `../reference/architecture.md`, so they are sequenced against anything else that does.

039 (#210) was closed unmerged and split into 041-043 once the review found it was one Register standing in for three unrelated tables - Assets, Transactions and Engineers - each of which reads and writes through its own pair of adapters. 041 lands first (038 and 041 both touch the same `tools/package.ps1:148` line 035/036 shared, so nothing in this half of the chain starts until it lands); 042 and 043 both depend on 041 and may run in either order relative to each other, never together. 044 and 045 lift a client-only window out of `notifier_app.py` and `storekeeper_app.py` respectively - independent of the register split, sequenced against each other only because both cascade into the same client-side rows. 046 is a plan ticket, not a build: it named the six clusters left in `server.py` once 041-043 land and deferred filing each one until the line numbers could be re-measured against the tree they leave behind. **That re-measurement is 050-055**, taken against the 9,826-line tree 043 left, and it moved two functions between clusters as well as every span: `_sync_admin_cfg` re-reads `admin_config.json` and is not the external asset sync its `_sync_` prefix put it under, so it stays in `server.py`; `_import_records_xlsx` restores records from an archive and is not the lookup's asset import, so it travels with 054 rather than 055 - and 046's rule-6 warning about it, the second writer into `transactions`, travels with it. All six rewrite `$SourceFiles` at `tools/package.ps1:149`, one line, so they are a chain merged one at a time in the order the table lists them, never two in parallel - the same reason 035 and 036 were sequenced over that line and 041 had to land before 042 and 043. 047 splits `tools/server-checks.py`, 18,758 lines and growing, once 043 has changed what its helpers take. 048 lifts `ui_kit.py`'s glass rendering into its own module, independent of the register chain but sequenced after 044 and 045 for the `architecture.md` row all three touch. 049 is the closing docs ticket: once every module above exists, `CODING_STANDARDS.md`'s "flat modules" line no longer describes the tree, and 049 is what corrects it - depends on the whole chain by construction, since it re-derives every count the earlier tickets stated.

They are filed on `origin` as #206 (035), #207 (036), #208 (037), #209 (038), #210 (039, closed, superseded), #211 (040), #215 (041), #216 (042), #217 (043), #218 (044), #219 (045), #220 (046), #221 (047), #222 (048), #213 (049), #224 (050), #225 (051), #226 (052), #227 (053), #228 (054), #229 (055), #230 (056), #231 (057), #232 (058) and #233 (059), all labelled `ready-for-agent` except where superseded or closed. 046 (#220) is closed: a plan ticket files no code, and what it planned is 050-055.

056 and 057 came out of 051 (#225) rather than out of a review: both are things a
ticket in a sequenced chain is right to walk past and wrong to leave. 056 is the
`SHIPS` regex in `tools/cascade-audit.py`, which names neither the three registers
nor - until each ticket adds it - the module that ticket created, so a commit to one
of them leaves a built server package reported as current; 041-043 created that gap,
050 and 051 both saw it and both left it, and the third pass is what made it a ticket.
057 is the dead stdlib imports each lifted cluster leaves at the top of `server.py` -
four by 7582d60, and however many 052-055 add. **Both sit behind 055**: 056 rewrites
the one `SHIPS` line all four of the remaining tickets edit, and 057 run any earlier
would only have to be run again.

058 and 059 are the same shape one pass later, each falling out of the ticket above
it. 058 came out of 057, whose scope measured the client modules and changed nothing:
the four names that measurement found - three left in `notifier_app.py` by 044, and
one in `storekeeper_app.py` that predates the numbered chain entirely - are what 058
removed. 059 came out of 056, which is what made `SHIPS` derive from `$SourceFiles`:
a module missing from that list was already absent from the package, and after 056 it
is invisible to the manifest drift check as well, so the one copy of "what a component
consists of" with no check on its contents needed one. **056-059 are merged.**

060-063 come out of a modularisation review (Sep 2026), a second pass over the same
shape of growth 035-059 already worked through once. 060
splits `server_gui.py`'s twelve console windows one-per-module, the same shape 041-043
gave the three registers and 046/050-055 gave `server.py`'s own remaining clusters. 061
and 062 lift the Storekeeper's Bulk window and its Propose/Import dialogs out of
`storekeeper_app.py`, the same shape 044/045 gave the Notifier's Remote Admin surface and
the Storekeeper's own Export window; 062 depends on 061 because both edit
`storekeeper_app.py` and the same cascade lines, the same reason 041 had to land before
042 and 043. 063 splits `tools/client-checks.py` into `tools/client_checks/` by check
group, the same shape 047 gave `tools/server-checks.py`. All four are independent of one
another except the 061/062 pair, and all four are sequenced after the 2.6.0 release
rather than against any ticket in this table, since none of them depends on code the
open chain above is still changing.

064 is closed and merged (`f3cf39b`). It was filed off a matrix of runs where the
1.75x/940px leg of `console.py`'s narrow-band group came and went on unchanged code, and
it read that matrix as the neighbouring groups; the cause was `resize()` settling on two
identical reads, which is a knife edge, and a third read makes the leg repeatable. Its
file is kept rather than deleted for two reasons: the measurements in it are why #214's
and #194/#201's recorded numbers got re-derived, and its last section - whether
`gate.py`'s `SHARD_CAP = {"client": 4}` still earns its place, now that eight client
shards come back green - is open and is tracked nowhere else.

065-072 come out of a console and deployment review (Sep 2026) and are features and
fixes, not a refactor chain, so they run in four lanes: {065, 066} rewrite `run_gui`'s
`ACTIONS` and `server_administration` and are sequenced; {067} is the deployment half of
#187 and touches only `tools/` and one `/health` key; {068, then 069 and 070 in either
order, never together} put what the server knows about IIS into `server_iis.py` and then
add the port's elevated half and the certificate install's; {071, then 072} give a System
Log row a `data` column and let the clients fill it. Every existence claim in them was
verified against the tree, not against an earlier ticket: the source-address fix and the
cutover's elevated `bind-cert.ps1` already exist, and 067 and 070 are about the
deployment and the install path not reaching them. 065 and 066 land before 060, which
moves the windows they edit and is filed to run after the 2.6.0 release these ship in.

106, 107 and 108 are the Transaction Origin. 106 is the server's Origin column; 107 shows the label where a decision is read and depends on it; 108 follows 107 because both edit `notifier_app.py` and the same Notifier description in `../reference/apps.md`.
