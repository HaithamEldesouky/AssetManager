# 023 - "Asset Server" in the words, not in the identifiers

**Type:** feature (naming) · **Depends on:** - · **Lands first**

## What changes

The product is an asset system, and the component that holds the assets is called "the
server" everywhere a person reads it - a word that names a role in a network, not this
application. It becomes **Asset Server** in every string a person sees: the Server GUI's
window title and health banner, the tray tooltip and menu, the installer's Server card and
its success popup, the Storekeeper's and the Notifier's Server Settings captions, and the
prose in `CLAUDE.md`, `CONTEXT.md`, the ADRs and the runbooks.

## What deliberately does not change

Every identifier. `AssetServer.exe` (37 references across `*.py` and `tools/*.ps1`), the
`AssetManagerServer` Windows Service (22), the IIS site and app pool names in
`deploy.json` and `iis.json`, `web.config`'s `processPath`, `server.py` itself, the
`rollback/<version>/` layout `update.ps1` writes, and `AssetManager_Setup.exe`.

A rename of those is a **cutover**, not an edit: every install on the network resolves the
exe by name, `update.ps1` stops a service by name, and `install-iis.ps1` writes a site
that IIS then owns. Doing it in the same ticket as the words would mean the words could
not land until the fleet had been re-installed. It is **ticket 033**, with its own runbook,
and it is deliberately last.

So this ticket is the one place where a display string and the identifier behind it are
allowed to disagree - the banner says Asset Server while the process is `AssetServer.exe` -
and the ticket says so rather than leaving a reader to wonder which is stale.

## Why it lands first

Every other ticket in this batch (024-032) rewrites lines in `CLAUDE.md` that this one
also touches - the architecture table's `server.py` row, the Server GUI bullets, rules 2,
6 and 11. Git merges by line, and those lines are 2000 characters each. Landing the rename
alone, first, means the nine tickets behind it rebase onto one settled wording rather than
nine of them conflicting on the whole line (`docs/agents/ticket-workflow.md`, "Two tickets
that cascade to the same line").

## Cascade

`CLAUDE.md`, `CONTEXT.md` (including the glossary - **Asset Server** becomes the term and
"the server" the synonym it says to avoid), `docs/adr/*` where the prose names the
component rather than the file, `docs/runbooks/*`, and the three client apps' captions.
`tools/cascade-audit.py` checks paths and names, not prose, so nothing there moves.

## Verification

`python tools/cascade-audit.py` exits 0. `python tools/server-checks.py` and
`python tools/client-checks.py` exit 0 - the window-size groups are the ones at risk,
since "Asset Server" is longer than "Server" in a banner and in a card caption.

## Not in this ticket

The exe, the service, the installer's own name, and any migration for an installed
machine. All of that is 033.

## As built

**The four apps.** `server.py`: the module docstring, the window title, the tray menu
header and both tray tooltips, the Quit dialog on both branches, the single-instance
message box and its title, and the `serve`-mode stderr prefix. `installer.py`: the Server
radio card and its description, the success popup, and the Desktop shortcut, now
`Asset Manager - Asset Server` to match `Asset Manager - Storekeeper` beside it.
`storekeeper_app.py`: Server Settings becomes **Asset Server Settings**, window title and
header. `notifier_app.py` needed nothing - its window is *Notifier* Settings and names the
component nowhere.

**A reinstall leaves the old shortcut.** The shortcut is written by name, so an install
over an earlier one puts `Asset Manager - Asset Server.lnk` on the Desktop beside the
`Asset Manager Server.lnk` that is already there. Both point at the same exe and both
work; the old one is deleted by hand. Not worth code - the installer has never removed a
shortcut, and a routine that deletes `.lnk` files by name on somebody's Desktop is a worse
thing to own than a duplicate icon.

**Three names were left alone that look like display strings and are not.**

- `_svc_display_name_` (`"Asset Manager Server"`) is what Services.MMC shows beside
  `_svc_name_`, and both are what an installed machine is registered under. A comment at
  that line says so, and says it waits for 033 - it is the one place in the file where the
  words and the identifier are allowed to disagree.
- The `Asset Manager` **firewall rule name** in the installer's success popup, and the
  `AssetManager\Server` install directory. Both are looked up by name on a machine that
  already has them.
- `"Server"` **as a stored value**: `LOG_COMPONENTS`, a System Log row's `component`
  column, and the `Admin (Server GUI)` actor written into `transactions.storekeeper` and
  into log rows. These are data. Renaming one splits the log in half at the moment it
  changes, and a filter over the column then matches one half - which is exactly the
  failure `cascade-audit.py` holds the Storekeeper's role label against.

**The docs sweep was narrowed, deliberately.** `CONTEXT.md` gains **Asset Server** as a
term at the head of Installations, with _Avoid_ naming "the server" and "the backend", and
every reference in that file moved onto it - it is the vocabulary file, so it has to be
consistent. `CLAUDE.md` gains the note under the architecture table that states the rule
and lists the frozen identifiers, and the `server.py` row, the Storekeeper's Server
Settings bullet and the installer's card bullet moved with the strings they quote.

What was **not** done is the ~150 remaining mid-sentence "the server" references across
`CLAUDE.md`, the ADRs and the runbooks. Rewriting them buys no clarity - the glossary is
what fixes a term, and every one of those lines is a 2000-character line whose whole
content would show as changed, burying the next nine tickets' diffs in a rename nobody
needs to read. The term is defined and the component-naming spots use it; the anaphora
behind them can move as those lines are edited for other reasons.

**The Server GUI keeps its name** throughout, in code and in prose. It is one window's
proper name rather than a word for the component, and it is written into a stored actor
string besides.

**Gates:** `cascade-audit.py` no drift, `server-checks.py` 113 groups, `client-checks.py`
12 groups - all three exit 0. `APP_VERSION` is untouched at 2.3.0, by instruction: it is
bumped once per release rather than once per ticket, so the four sources still agree and
`package.ps1` is satisfied.
