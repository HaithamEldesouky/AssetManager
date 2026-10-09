# 012 - Notifier: an Engineer with an Own Password opens Settings, and the URL changes offline

**Type:** feature · **Depends on:** 010 · **Blocks:** 014 (same `common.py` line)

## What is asked

1. Once an Engineer has set or been given an Own Password at least once, opening Settings
   no longer demands the admin password.
2. The Server URL can be changed **even when the server is unreachable**.
3. Changing a password still requires the server to be online.

## Where it stands today

`AdminAuthNotifier._verify` (`notifier_app.py:930`) calls `common.verify_password`, and
Settings opens only when the answer says `admin: true` **or** the Engineer's profile
grants `open_settings` (`notifier_app.py:939-940`). The default profile grants neither, so
an Engineer with an Own Password but no profile is refused.

Both checks are **network calls**. With the server unreachable, `verify_password` raises
and Settings cannot be opened at all - which is exactly when somebody needs to correct the
Server URL. That is the chicken-and-egg this ticket breaks: the one setting that could fix
an unreachable server is behind a check that needs a reachable server.

## Scope

- **Opening Settings:** an Engineer who holds an Own Password (`has_password` on
  `GET /members`, which the client already reads) opens Settings with it. Whether this
  *replaces* the `open_settings` permission or sits beside it is 010's business - agree it
  there, and do not leave two rules that disagree.
- **Offline URL change:** when the server cannot be reached, allow the Server URL field to
  be edited and saved. What authorises it offline has to be stated, not skipped: there is
  no way to check any password without the server, so the honest options are (a) allow it
  and say so on the window, or (b) accept a locally-cached proof. **Recommended: (a), and
  narrow it to the URL field alone** - nothing else on that window may be changed offline,
  because the URL is the only setting whose wrongness is what made the server unreachable.
- **Password change stays online.** `OwnPasswordWindow` already posts
  `/auth/change_password` and already says so when the server cannot be reached
  (`notifier_app.py:1105`) - leave that exactly as it is. Only the server knows whether an
  Engineer has an Own Password at all.
- **Nothing here may stop a Transaction being confirmed** - the standing rule for this app.

## Cascade

- The Notifier's **Own password**, **Access profile** and **Replacing a Temporary Own
  Password** bullets in `CLAUDE.md`.
- The `common.py` row of the architecture table **if** the offline path lands in
  `common.py` - that row is one very long line, which is why 014 is sequenced after this
  rather than run beside it.
- Run `client-checks.py`; its "which window opens" group already asserts what the Admin
  Login dialog opens, so extend that group rather than writing a new one.
