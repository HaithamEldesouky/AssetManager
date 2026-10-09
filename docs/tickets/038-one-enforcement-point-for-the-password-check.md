# 038 - One enforcement point for the password check

**Type:** refactor · **Depends on:** 036 · **Found by:** architecture review, Sep 2026 · **Issue:** [#209](https://github.com/HaithamEldesouky/AssetManager/issues/209)

## Finding

There is no decorator and no middleware for authorisation. `_admin_password_ok`
(`server.py:2698`) is called from roughly 50 places, each route and each window guarding
itself by hand. The only `@app.before_request` is `_hold_writes_during_maintenance`
(`server.py:5342`), which is the maintenance gate, not auth.

Two consequences:

1. **A route is guarded only if its author remembered.** Nothing in the source
   distinguishes a route that is unauthenticated on purpose - ADR-0002 says the transaction
   endpoints are - from one that simply forgot.
2. **Delegation reaches 3 routes of 48.** `_authorise` and `_remote_authorise`
   (`server.py:2737-3188`) are called from `POST /members` (6574), `POST /admin/mail`
   (10094) and `POST /admin/notify_rules` (10183). The other 45 cannot delegate at all,
   which is why every new remote-admin capability needs its own wiring.

## Scope

1. **Every route declares the credential it wants.** Admin password, own password,
   capability password, or explicitly none.

2. **One module decides**, and is the only caller of `_admin_password_ok` and the
   capability checks.

3. **A route that declares nothing fails the gate.** `tools/server-checks.py` already has
   `check_authorisation_is_in_the_one_enforcement_point` (9142), which parses the source -
   extend it to enumerate routes and refuse an undeclared one. Unauthenticated becomes a
   stated fact, not an absent line.

4. **Delegation becomes available to every route** by declaration, rather than by being
   wired in one at a time.

## Not in this ticket

- **Reversing ADR-0002, 0006 or 0015.** Read all three before shaping the interface. The
  transaction endpoints stay unauthenticated; they just say so.
- Changing any password format. ADR-0008's two coexisting formats are untouched.
- The console door, which 036 moved and which is a different credential.

## Cascade

- `CLAUDE.md` - rule 7 and rule 8 wording, if the enforcement point changes where a
  permission name is read.
- `docs/reference/api.md` - the API table gains the credential each endpoint wants.
- ADR-0002, ADR-0006, ADR-0015 - each gets a line pointing at the new module. Do not
  rewrite their decisions.
- `docs/reference/apps.md` - the Capability Passwords bullet.
- `CONTEXT.md` - if the module introduces a term, it goes in the glossary.

## Verification

- `ast.parse()` every file touched.
- `py -3.12 tools/gate.py --all`.
- Hit every admin endpoint with no password, a wrong password and a right one, and confirm
  401 / 401 / 200. This is the check that must enumerate routes rather than sample them.
- Confirm a delegated capability now works on a route that previously could not delegate.
