# 069 - Changing the port moves the IIS binding

**Type:** feature · **Depends on:** 068 (adds to the module it creates) · **Found by:** console review, Sep 2026 · **Issue:** [#244](https://github.com/HaithamEldesouky/AssetManager/issues/244)

## Finding

Under IIS the port is the site binding, and the console knows it: Server Settings'
Change Host / Port (`do_save_cfg`, `server_gui.py:5493-5517`) saves the number into
`server_config.json` through `_save_server_cfg` (`server.py:916`) and then tells the
Admin, in a message box, to go and run `tools\install-iis.ps1 -Port <n>` by hand
(`:5507-5515`). ADR-0001's last consequence records this as the design. `POST
/admin/server_config` (`server.py:6203`) answers "Restart the server to apply changes",
which under IIS applies nothing.

The certificate already has the shape this needs. C4's cutover writes files in process
and spawns an **elevated half**, `tools\bind-cert.ps1`, through `_bind_cert_command`
(`server_cert.py:443`), because the app pool identity cannot touch a binding and
`install-iis.ps1` is a full install with side effects nobody asked for
(`bind-cert.ps1`'s own header says both). The port has no elevated half.

The client side needs nothing: while the old listener is up, `/health` advertises the
saved port as `next_port` (`server.py:4136-4142`), each client records it on its 15s
tick and falls back to it, then to `last_known_port`, when the old port dies
(`common.py:569-609`; `iis-cutover.md:214-226`).

## Scope

1. **`bind-port.ps1`**, under `tools/` as a sibling of `bind-cert.ps1`, sharing `_deploy.ps1`'s
   helpers, `SupportsShouldProcess`, ASCII only. Parameters `-InstallDir`, `-Port`,
   `-SiteName` (default from `iis.json`), `-Grace` (seconds, default 120). Steps, in
   this order, each idempotent:
   1. read-modify-write `server_config.json` `port` (the shape `install-iis.ps1:840-870`
      uses; never a fresh object - it holds `ssl_enabled`);
   2. add an https binding on the new port **beside** the old one and bind the same
      certificate to it (`IIS:\SslBindings\0.0.0.0!<new>`, thumbprint from
      `Get-BoundCertThumbprint` on the old port);
   3. firewall rule for the new port, the same rule shape `install-iis.ps1` writes;
   4. `iis.json` `port` (this one writes it: unlike a rebind, the port is a fact
      `iis.json` records and this script is now a writer of it - `bind-cert.ps1`'s
      "writes no iis.json" reasoning does not carry);
   5. `Restart-WebAppPool` so the process re-reads `PORT` and `/health` reports the
      new one - `HTTP_PLATFORM_PORT` is IIS's loopback port and does not change;
   6. wait `-Grace` with the old binding still answering - this is the window in which
      `/health` on the old port says `next_port` and every online client records it;
   7. remove the old binding and its SslBinding; print old and new.
2. **`server_iis.py`** (068): `_bind_port_command(port, install_dir=None)` beside
   `_bind_cert_command`, same list shape, same reason the docstring there gives.
3. **Console**: under IIS `do_save_cfg` spawns it elevated after saving, with the same
   refused-elevation path the cutover has (`server_gui.py:5719`, `:5794`): the exact
   command shown to paste. The warning label `:5482-5485` and the `Save` caption change
   to say what now happens. Off IIS nothing changes.
4. **`POST /admin/server_config`**: under IIS the note says the binding moves when the
   console applies it, not "restart the server"; the route itself does not spawn (it
   runs as the pool identity and cannot).
5. One System Log entry, `server.port_moved`, `warn`, naming old and new, written
   before the spawn for the reason `_cut_over_cert`'s docstring gives about restarts.

## Not in this ticket

- Changing the host. `HOST` under IIS is `127.0.0.1` from HttpPlatformHandler and the
  field is what the GUI probes; unchanged.
- Running the script from `update.ps1`. It has no port to move.

## Cascade

- `docs/reference/tooling.md` - a `bind-port.ps1` section beside `:570`'s
  `bind-cert.ps1`; `install-iis.ps1`'s section notes it is no longer the only mover.
- `docs/runbooks/iis-cutover.md:214-226` "Changing the port" - rewritten around the
  console doing steps 1-7.
- `docs/reference/api.md:79` - the POST row's note.
- `docs/adr/0001:31` - the sentence naming `install-iis.ps1` as what moves the port
  is corrected; **a new ADR-0021**, "the console moves the binding through an elevated
  half", generalising what ADR-0020 decided for the certificate to the port.
- `docs/system-log-events.md` row and `EVENT_SENTENCES` phrase for `server.port_moved`.
- `docs/reference/files-on-disk.md` - `iis.json` gains a second writer.
- `tools/cascade-audit.py` `_EVENT_SOURCES` if the call lands in `server_gui.py`.

## Verification

- `bind-port.ps1 -WhatIf` prints seven steps and changes nothing.
- On a test IIS: two bindings during the grace, one after; `/health` on the new port
  reports it as `port`; a client left on the old URL follows within one tick after the
  old binding goes.
- Refused elevation shows a command that, pasted, does the same thing.
- `py -3.12 tools/gate.py --all`; `ast.parse()` on every Python file touched.
