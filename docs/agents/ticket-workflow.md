# Ticket workflow

One ticket, one change, dependencies verified before anything is written.

## Splitting

Work that is more than one change gets split into tickets before any code is written —
one ticket per feature, per bug fix, per refactor, and never a ticket that is two of
those. A ticket that cannot be described without the word "and" is usually two tickets.

Each ticket says what it changes and which tickets it needs first. Verify every
dependency by reading the code or the depended-on issue; the order tickets were written
in is not the order they unblock in, and a dependency nobody checked is the one that
turns out to be circular.

Tickets live where `issue-tracker.md` says, labelled as `triage-labels.md` describes.

## One ticket at a time

Working a ticket in the current session is the default. Do not spawn a background task on
your own — a session per ticket costs tokens that may not be wanted spent. Say which
tickets are ready to start, offer a task for each, and spawn only the ones approved, each
prompt self-contained: paths, issue number, and enough context to act without the
conversation that split them. A ticket that does get its own task gets its own session and
its own worktree, so two tickets never share a working tree or a branch.

**Ready** means the ticket's dependencies are both: closed, and merged. Closed but
unmerged is not ready — a closed ticket whose branch never landed leaves the code it
promised missing. Review is not part of the test in this repo, because a review here only
happens when somebody asks for one (`pull-requests.md`).

A branch that has a ticket ends with its number — `fix/stale-cache-42` or `fix/stale-cache-#42` — because that
trailing number is what `tools/land.py` closes the issue by. A branch without one lands the same way:
its ticket is left open and the script says so, rather than reading a hex suffix like
`-cc0d96` as a ticket number.

## Planning waves

Once tickets are written, `/ticket-plan` sorts the open ones into waves and prints a start
prompt for each ticket that is ready, plus one fan-out prompt per group that can run in
parallel, each ticket in its own worktree. It spawns nothing. The steps live in the global
`ticket-workflow` skill; the Ready test and the collision rules it applies are this file's.

## Blocked tickets are refused

Asked to work a ticket whose dependencies are not both: name the blocking ticket and
which of the two it is missing, write no code, and stop. Say plainly that this is a rule
being followed and not an impossibility — if the answer is to proceed anyway, proceed.

The point is not ceremony. A ticket built on an unmerged dependency is rebased or
rewritten later by whoever merges it, and the second ticket's diff is then a guess about
what the first one will look like once it lands.

## Two tickets that cascade to the same line

The cascade rule in `../../CLAUDE.md` sends a change to every place recording the same
fact, and several of those places are one very long line. Git merges by line, so two
tickets that both cascade into one of them do not merge — they conflict, and the conflict
is the whole line, with no way to see which side changed what.

The long lines that bite are the single-row entries in `docs/reference/architecture.md`
(the `ui_kit.py` and `common.py` rows), the Remote Admin bullets in
`docs/reference/apps.md`, and the PowerShell traps paragraph in
`docs/reference/tooling.md`. Measure the line before citing its length.

So a collision there is a dependency, even where the code is independent: sequence the
two tickets rather than starting both, and say which line they share when writing them.
The trap is that the code looks unrelated — two tickets touching different client apps
land in the same `common.py` row.

Landing a ticket the session it goes green is the other half, and it is the cheaper half.
A branch that lives an hour conflicts with nothing; one that sat while `main` took four
merges is what produced the only hand-resolved conflict this repo has had.

## Writing the code

Read `../CODING_STANDARDS.md` first and follow it. Where it is silent, follow the code
around what is being changed; reach for a general best practice only where the repo has
no habit of its own to copy.

## Finished

A ticket is finished when its coverage is written, not when the suite has run. New
behaviour on the server or the wire gets a check in the same change and a bug fix gets
the check that would have caught it; `../CODING_STANDARDS.md` says whether it belongs in
`tools/server-checks.py` or `tools/client-checks.py`.

Running the suite is a separate step, done on request rather than by default. Run it when
asked and say plainly whether it passed. A ticket is never called green on a suite nobody
ran.

## One ticket, one commit on `main`

A ticket lands as **one squash commit**: `git merge --squash <branch>` on `main` and
then a commit of its own, so `git log main --oneline` reads as the list of tickets this
repo has shipped and nothing else. The branch keeps its own history and is not rewritten
- what stops travelling to `main` is the intermediate state every branch here carries by
the time it lands: the half-written check, the fix to it, and the merge of `main` back in
that `pull-requests.md` requires before a push.

It is a rule rather than a taste, because of what `main`'s history is actually read for.
The cascade rule sends one fact to every place recording it, and the question asked
afterwards is always *which change moved this line* - `git blame` and `git log -L` over a
2100-character bullet under `docs/reference/` answer with a commit, and a commit that is one
ticket names the reason where `wip` and `merge main` name nothing. A package manifest's
commit is the second reader: `package.ps1` stamps the commit a payload was built from, so
one commit per ticket is what makes that stamp something a person can describe.

The commit message says what changed and why, and closes the issue by number so the
tracker and `main` agree without anybody doing it by hand.

Two things it does not change. A **chain** is still merged one at a time, dependency
first (below): squashing decides what one ticket looks like on `main`, not whether two
may land together. And nothing here rewrites a commit already on `main` - a ticket that
landed is landed, and a correction to it is the next ticket's commit.

## Merging a chain, in order

A chain of tickets is merged one at a time, dependency first: the ticket nothing depends
on goes in, is reviewed if a review was asked for, and only then does the ticket that
stood on it get merged. Then the next.

Never two tickets from one chain in parallel, and never the later one first. Merging out
of order puts code in `main` that reads a thing that is not there yet, and the branch that
would have added it is now rebasing onto the mess.
