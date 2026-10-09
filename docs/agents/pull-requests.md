# Push, pull request, review — in this repo

**This file overrides the global rules.** Where the global instructions say a draft pull
request is proposed after every push, and the review runs unless a skip applies, this
repository says neither happens on its own. Two things still hold, because they are not
about announcing work: merge `main` into the branch before pushing, and resolve every
conflict before going further.

## No pull request by default

Push the branch and stop. Do not open a pull request, do not propose one, do not ask
whether to open one — silence here is the expected behaviour, not an omission.

Somebody opens it when the work is ready to be looked at, and in this repo that is often
not the session that wrote the code. Open one only on a direct instruction to open it.

## No code review unless it is asked for

Do not run `mattpocock-skills:code-review`, and do not offer to. On a direct instruction
it runs as the global rules describe: against the merge-base, reporting standards and
spec, standards meaning `../CODING_STANDARDS.md`.

This is a deliberate trade. Code can reach a branch here, and `main`, without a review
having seen it. Whoever asks for the review decides when that matters.

## Landing it

The push above sends the branch up. It is not the work landing, and in this repo nothing
else lands it either — there is no pull request waiting to merge it.

Once the work is resolved: close its ticket, merge the branch into local `main`, push
`main`, then delete the branch and the worktree it sat in. Local `main` first and the
remote second, so what goes up is a `main` that has already been seen here.

The tree is left clean. A closed ticket with its branch still sitting beside it is the
state this section exists to prevent, and it is likelier here than anywhere else: with no
pull request closing the loop, nothing tidies up unless it is done deliberately.

`tools/land.py` does exactly that, in order, and refuses rather than guessing: a dirty tree, a
conflict with `main`, `main` held by another worktree, or a red suite each stop it before
anything is pushed, and it names what it found. Run it when the work is finished — `py -3.12 tools/land.py`,
or `--dry-run` first to see the plan without touching anything.

It does not commit. A commit carries a message somebody chose, and a script that stages
whatever it finds will eventually sweep another session's half-written file into `main`.
Commit first, land second.

## What is still required

- `main` merged into the branch before the push, so nothing is pushed against a stale base.
- Every conflict resolved first. A branch with a conflict is not pushed.
- `../CODING_STANDARDS.md` followed while writing.
- The branch landed on local `main`, `main` pushed, the branch and its worktree then
  deleted — see "Landing it" above.
- One ticket per change, worked in the current session unless a background task for it is
  approved, merged in dependency order — see `ticket-workflow.md`.
