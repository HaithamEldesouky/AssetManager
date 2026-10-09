# 068 - What the server knows about the IIS in front of it becomes a module

**Type:** refactor · **Depends on:** nothing · **Found by:** planning 069 and 070, Sep 2026 · **Issue:** [#243](https://github.com/HaithamEldesouky/AssetManager/issues/243)

## Finding

Five functions answer one question - *is there an IIS in front of this process, and what
has it bound* - and they sit in two files under two names:

| Function | Where | What it answers |
|---|---|---|
| `_iis_host()` | `server.py:408` | the site and pool `iis.json` records, decoded utf-8-sig |
| `_port_serves_tls()` | `server.py:450` | does the port answer a TLS handshake |
| `_iis_tls_bound()` | `server.py:500` | is a certificate bound, by `iis.json` or by asking |
| `_bind_cert_command()` | `server_cert.py:443` | the elevated command that moves the binding (C4) |
| `_remote_tls_ok()` | `server.py:3217` | is this request encrypted, by `is_secure` or by IIS |

069 adds a second elevated command (the port) and 070 a third act (recycle the pool).
Neither is about certificates, so `server_cert.py` is the wrong home, and `server.py`
is what #224-#229 have been emptying. The shape those tickets set - one module, one
`bind()` handed the names that stay in `server.py` - fits: `iis.json`'s path is
`BASE_DIR`'s, and nothing here reaches the database.

## Scope

1. `server_iis.py`: the five functions above, moved verbatim, plus `IIS_STATE_PATH`
   (`server.py:333`), the `iis.json` path `_iis_host` reads. `bind(server_module)`
   handed `BASE_DIR`, `PORT`, `SSL_CERT_PATH` and whatever else `grep` finds the five
   reading out of `server.py`'s globals - list them in the commit.
2. `server.py` imports it and rebinds the five names so every existing call site and
   `server_gui.py`'s `S._iis_host()` keep working unchanged. `server_cert.py` imports
   `_bind_cert_command` back from it rather than defining it.
3. No behaviour change. A move.

## Not in this ticket

- `_bind_port_command`, `_recycle_pool_command` - 069 and 070 add them to the module
  this creates.
- `_client_addr()` - it is about the request, not about IIS, and stays.

## Cascade

The "new module beside an app" row of `CLAUDE.md`, in full:

- `tools/gate.py:87` `MAP` - a row for `server_iis.py` onto `("server",)`.
- `tools/server_checks/stage.py:211` and `:680` - both staging tuples.
- `tools/client-checks.py:259` `SRC_FILES` - server module, so **not** this list;
  confirm and say so.
- `tools/package.ps1:152` `$SourceFiles`; `tools/dev-run.ps1:206`
  `New-AppDir "server"` list.
- `tools/cascade-audit.py:1983` `_EVENT_SOURCES` - only if a `_log_event` call moves;
  grep before deciding.
- `CLAUDE.md` "The files" table - one row, in the shape the `server_clients.py` row has.
- `docs/reference/architecture.md` - the Asset Server section's module list.
- `docs/adr/0020` names `_bind_cert_command` as `server_cert.py`'s - one sentence.

## Verification

- `ast.parse()` on every file touched; headless `import server` still succeeds.
- `py -3.12 tools/gate.py --all` - the staging lists are what this can break.
- `tools/server_checks/stage.py`'s import of `server_cert` finds `_bind_cert_command`
  through the new import.
