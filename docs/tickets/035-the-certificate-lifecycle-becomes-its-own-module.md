# 035 - The certificate lifecycle becomes a module of its own

**Type:** refactor · **Depends on:** nothing · **Found by:** architecture review, Sep 2026 · **Issue:** [#206](https://github.com/HaithamEldesouky/AssetManager/issues/206)

## Finding

`server.py` is 18,703 lines in one scope: 261 top-level functions, 48 routes and the whole
Server GUI. The GUI is one contiguous block - `server.py:10257` to `18424` - and lifts out
cleanly except for one thing sitting in the middle of it.

`server.py:15546-16064` is the certificate lifecycle: `_cert_to_pem`, `_cert_fingerprint`,
`_cert_names`, `CERT_NEXT_DAYS`, `_stage_new_cert`, `_push_next_cert`,
`_clients_behind_staged`, `_bind_cert_command`, `_cut_over_cert`, `_export_public_cert`.
519 lines. It is **not** GUI - it imports no tkinter, builds no widget, and the only `root`
in it is an install directory (`server.py:15909`).

**And two routes call into it**, from above:

| caller | line | callee | defined at |
|---|---|---|---|
| `GET /clients` | 7802, 7803 | `_cert_fingerprint()` | 15632 |
| the push-cert route | 7871 | `_push_next_cert()` | 15803 |

Python resolves those at call time, so it works. But it means the block between 10257 and
18424 is not one concern, it is two, and lifting the GUI out with the certificate code
still inside it would move code the routes depend on into a module the routes must then
import - while that same module imports the routes' own helpers. That is the circular
import, and it is the reason this ticket lands before 036 rather than inside it.

Everything else in the region is console-only. Verified by call site:

- `_gui_snapshot`, `_transaction_log_rows`, `_transaction_client`, `_console_unsaved`,
  `_track_unsaved`, `_cert_to_pem`, `_cert_names`, `_stage_new_cert`,
  `_clients_behind_staged`, `_bind_cert_command`, `_cut_over_cert`, `_export_public_cert`
  - no caller below 10257.
- `run_gui()` is called once, at `server.py:18703`, the last line of the file.
- `THEME` is referenced nowhere before 10257.

## Scope

One new file, `server_cert.py`, beside `server.py`.

1. **Move `server.py:15546-16064` into it verbatim.** No behaviour change, no signature
   change, no renaming. A diff that is anything but a move plus an import is the wrong
   diff.

2. **`server.py` imports it** at module level. It is headless-safe by inspection - no
   tkinter anywhere in the block - so it does not need the deferred-import treatment
   `CODING_STANDARDS.md` requires of drawing code.

3. **The paths it reads stay resolved the way they are.** `SSL_CERT_PATH`,
   `SSL_CERT_NEXT_PATH`, `SSL_KEY_NEXT_PATH` and `BASE_DIR` are `server.py`'s. Pass them
   in or import them back; do not re-derive an install directory in the new file, which is
   the failure `CODING_STANDARDS.md` "Paths" is standing in front of.

## Not in this ticket

- Lifting the GUI out. That is 036, and it is sequenced behind this one.
- Any change to ADR-0020's two-phase rotation, or to what the cert functions do.
- `_console_unlock` and `simple_password_prompt`, which are console door and go with 036.

## Cascade

- `CLAUDE.md` - "The files" table gains a row.
- `docs/reference/architecture.md` - the same row, in full.
- `docs/CODING_STANDARDS.md:12-22` "Where code goes" - gains the module. **While in there,
  line 14 still says "One exe, three modes"; rule 12 retired the app exes at #061.** Fix it
  in this commit.
- `tools/package.ps1:147` - `$SourceFiles = @("server.py", "ui_kit.py", "run_server.py",
  "applaunch.py")`. **`server_cert.py` must join it or the release ships a server that
  cannot start.** One line, so 035 and 036 conflict here if run together - which is why
  they are sequenced.
- `tools/server-checks.py` - stages `server.py`; must stage the new file too.
- `docs/reference/files-on-disk.md` if a new file is written beside the app. It is not, but
  check.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py --all`.
- Start the server, `GET /clients`, confirm `served` and `staged` fingerprints still come
  back - that is the route that reaches across the old seam.
- Open the Server GUI's certificate controls in Server Settings and confirm a stage and an
  export still work.
