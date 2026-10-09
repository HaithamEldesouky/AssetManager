# 104 - The console reads an IIS HTTPS server as it is

**Type:** bug · **Depends on:** none · **Issue:** [#280](https://github.com/HaithamEldesouky/AssetManager/issues/280)

## Finding

Reported on the 2.9.1 install on asset-server, behind IIS on port 443, with
`iis.json` carrying a `cert_thumbprint` and `server_config.json` carrying no
`ssl_enabled` key. The server is healthy - `GET https://asset-server:443/stats`
answers 200 in 0.1s - and the console says three false things about it.

**1. The banner reads NOT RESPONDING / "nothing is answering".** `refresh_stats`
in `server_gui.py` probes `https://127.0.0.1:PORT/stats` through a `requests`
session whose `HTTPAdapter.init_poolmanager` hands urllib3 an `SSLContext` with
`CERT_NONE`. requests 2.32.3 (the version `requirements-client.txt` pins)
defeats that: `verify` defaults to `True`, so the adapter passes
`cert_reqs="CERT_REQUIRED"` on every request and urllib3 applies it over the
context. Reproduced against the live server with the probe's own code:

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: self-signed certificate'))
```

The `except Exception: pass` swallows it, `set_health(False)` runs, and the
counts read `-`. The same context through `http.client.HTTPSConnection(...,
context=ctx)` answers 200 with the counts. `tools/server_checks/tls.py` did not
catch it because `_requests_stub` replaces `requests` wholesale: it asserts the
URL and that the source says `CERT_NONE`, never that a handshake against a
self-signed listener succeeds.

**2. `_port_locked` in `gui_settings.py` has the same adapter**, so over HTTPS
its `/health` read fails the same way, the `http://` fallback fails against a
TLS port, and it answers False whatever the server says.

**3. Server Settings' SSL Certificate panel reads "Inactive (HTTP)".**
`gui_settings.py` computes `_ssl_on` from `S._SERVER_CFG.get('ssl_enabled')`
alone. Under IIS that key is written by nothing (see `_iis_tls_bound`'s
docstring in `server_iis.py`), which is the #176/#185 defect: the banner, the
tray, `/health`'s `ssl` key and `_remote_tls_ok` were all moved onto
`_iis_tls_bound()`, and this panel was missed.

## Scope

1. **One loopback probe helper, no `requests`.** Both probes (`refresh_stats`
   `/stats`, `_port_locked` `/health`) make their HTTPS request with
   `http.client.HTTPSConnection("127.0.0.1", S.PORT, context=ctx, timeout=2)`
   where `ctx` is the `CERT_NONE` / `check_hostname=False` context they build
   today; plain HTTP stays as it is. Keep the long "verifies nothing, on
   purpose" comment in `refresh_stats` - its reasoning is unchanged, only the
   transport moves. Put the shared request in one function in
   `server_gui.py` beside `refresh_stats`'s module-level neighbours and have
   `gui_settings.py` reach it as `S.<name>` if that reads cleaner than two
   copies; two short copies are acceptable if the helper would need a
   `bind()` change. Never write `verify=False` (rule 1's grep).
2. **The SSL Certificate panel asks who terminates TLS.** In
   `server_settings`, when `_iis is not None`, `_ssl_on` is
   `S._iis_tls_bound()` and the status does not require `ssl_cert.pem` to
   exist (under `-PfxPath`/`-CertThumbprint` it correctly may not). Off IIS
   the expression is exactly today's. Mirror `_ssl_active` in `run_gui`
   (`server_gui.py`, "Who is terminating TLS").

## Not in this ticket

- The source address every client shows in Connected Clients. It was checked in
  the same report: `_client_addr` in `server.py` reads the
  `X-Forwarded-For` IIS sets from `REMOTE_ADDR`, and the value it shows
  (198.51.100.29 for a laptop whose own address is 198.51.100.11) is the NAT /
  VPN gateway between the client subnet and 192.0.2.0. Working as designed.
- Any `door(...)` line, endpoint or wire field.

## Coverage

The check that would have caught it: in `tools/server_checks/tls.py`, stand up a
real TLS listener on loopback with a freshly generated self-signed certificate
(`make_cert` in `tools/_devtools.py` already writes one), point
`S.PORT` at it, and assert `refresh_stats` calls `set_health(True)` and
`_port_locked` returns the served `port_locked`. Drop or narrow
`_requests_stub` to what still uses `requests`; keep the source assertions on
`CERT_NONE` and on no credential crossing the probe. Add a check that the SSL
Certificate panel reads Active (HTTPS) with `_iis_host()` returning a record
with a thumbprint and `ssl_enabled` absent.

## Cascade

- `docs/reference/apps.md` - the Server Settings bullet, if it says what the SSL
  status reads from.
- `APP_VERSION` patch bump to 2.10.1 in all four sources.
- Server payload rebuild at release; no client payload changes.

## Done when

`py -3.12 tools/gate.py` passes; on an IIS install with a thumbprint in
`iis.json` and no `ssl_enabled`, the console banner reads RUNNING with live
counts and the SSL Certificate panel reads Active (HTTPS).
