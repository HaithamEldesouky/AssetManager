# 070 - Installing or removing a certificate under IIS moves the binding, or refuses

**Type:** bug fix · **Depends on:** 068 (adds to the module it creates) · **Found by:** console review, Sep 2026 · **Issue:** [#245](https://github.com/HaithamEldesouky/AssetManager/issues/245)

## Finding

Server Settings' **Install Certificate** (`do_install`, `server_gui.py:5969-6018`)
writes `ssl_cert.pem` and `ssl_key.pem`, sets `ssl_enabled` in `server_config.json`,
logs `cert.installed`, and calls `_restart_server` (`:5930-5968`) - which asks `sc
query` for the Windows Service and, finding it stopped (it is disabled under IIS,
ADR-0001), falls through to `os.execv` of the **GUI process**. Under IIS that restarts
a monitor window. The site keeps serving the certificate it had; the pool is never
recycled; the popup says "Clients connect to: https://...".

**Remove Certificate** (`do_remove`, `:6019-6043`) deletes both files and sets
`ssl_enabled=False`. Under IIS the site is still https, `GET /cert` now 404s, and every
pinned client is stranded (rule 1) - the exact outage ADR-0020 exists to prevent.

The cutover (C4) does this right: `_cut_over_cert` moves files, and the window spawns
`_bind_cert_command` elevated (`:5719`). Install is the same act one step earlier with
no spawn. And `/health`'s `ssl` (`server.py:4143`) answers from the config flag plus
file presence, which under IIS may say `false` over a site that is serving TLS -
`_port_serves_tls()` (`server.py:450`) already knows the truth and is not asked.

## Scope

1. **Install under IIS**: after writing the pair and logging, spawn `_bind_cert_command`
   elevated exactly as the cutover does, with its refused-elevation path. No
   `_restart_server`. Popup says the binding moved, or shows the command to paste.
2. **Remove under IIS**: refused, before anything is deleted, with the reason on the
   dialog: IIS terminates TLS, so removing the files does not turn https off and does
   strand every pinned client. Names `install-iis.ps1` as the only thing that changes
   what the site serves. Off IIS unchanged.
3. **`_restart_server`** gains the IIS branch it lacks: where `_iis_host()` is not
   None, `_recycle_pool_command()` (new, in `server_iis.py`, elevated
   `Restart-WebAppPool <pool>`), never `os.execv`. Every existing caller benefits.
4. **`/health` `ssl`** answers `_port_serves_tls()` where `_iis_host()` is not None,
   the flag-and-files test otherwise. Additive in meaning, same key.
5. `bind-cert.ps1` recycles the pool after rebinding, so a rebind and a process that
   re-reads its files are one act. `update.ps1` already cycles the pool itself.

## Not in this ticket

- The staged rotation (C1-C5). Unchanged.
- Any change to what `install-iis.ps1` does with a certificate.

## Cascade

- `docs/reference/apps.md` Server Settings bullets - Install and Remove under IIS.
- `docs/reference/api.md:37` - `/health` `ssl` wording.
- `docs/reference/tooling.md:570` - `bind-cert.ps1` now recycles.
- `docs/adr/0020` - one paragraph: Install is C4 without C1-C3 and takes the same
  elevated half; Remove is refused under IIS.
- `docs/system-log-events.md` - if a refusal is logged, its row and phrase; otherwise
  none.
- `tools/server_checks/certificates.py:212-226` asserts on `client_list` and the
  cutover; add the assertion that `do_install`'s IIS branch reaches
  `_bind_cert_command` and `do_remove`'s refuses.

## Verification

- On a test IIS: Install shows the new fingerprint bound (`Get-BoundCertThumbprint`)
  and the pool recycled; Remove is refused with the files untouched; `/health` `ssl`
  is `true` with `ssl_enabled` false in the file.
- Off IIS: Install and Remove behave as today, `_restart_server` unchanged.
- `py -3.12 tools/gate.py` on the diff; `ast.parse()` on every file touched.
