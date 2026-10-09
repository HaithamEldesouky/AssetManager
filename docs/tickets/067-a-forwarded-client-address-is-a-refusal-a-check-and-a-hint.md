# 067 - A forwarded client address is a refusal, a check and a hint, not a warning

**Type:** bug fix · **Depends on:** nothing · **Found by:** Connected Clients recording loopback on asset-server, Sep 2026 · **Issue:** [#242](https://github.com/HaithamEldesouky/AssetManager/issues/242)

## Finding

The code that records where a request came from is right and has been since #187.
`_client_addr()` (`server.py:3159-3214`) returns the TCP peer, and reads
`X-Forwarded-For` **only** when that peer is loopback (`_LOOPBACK_PEERS`, `:3150`) -
which under HttpPlatformHandler is every request (ADR-0001). The header is written by
IIS itself: `tools/install-iis.ps1:696-756` adds a URL Rewrite rule
`AssetManagerClientAddress` that sets `HTTP_X_FORWARDED_FOR` from `{REMOTE_ADDR}`,
replacing anything a caller sent. The client sends no address of its own
(`_CHECKIN_FIELDS`, `server_clients.py:123`; `common.py:918`). `clients.address` and
`system_log.address` are what the window and the log show.

What is wrong is the deployment's half of it. URL Rewrite is a separate download, and
where it is absent `install-iis.ps1:368-380` **warns** and goes on - the site starts,
no header arrives, `_client_addr()` falls through to the peer and every row says
`127.0.0.1`. `tools/deploy-checks.ps1` never asks (zero matches for `forwarded`), and
the Connected Clients window (`server_gui.py:2930`) shows a column of loopbacks with
nothing beside it saying why. Nothing in the tree tells an operator the one thing they
need to hear: the module is missing, install it, re-run the script.

## Scope

0. **First, on asset-server, before any code**: `Get-WebGlobalModule` for
   `RewriteModule`; `Get-WebConfiguration -Filter system.webServer/rewrite/rules` on
   the site `iis.json` names; one check-in from a laptop and the row it leaves. Record
   the answer in the ticket's commit message. If the rule is present and the address is
   still loopback, stop and re-plan - the finding above is wrong.
1. `install-iis.ps1`: URL Rewrite becomes a **refusal**, the same shape as
   HttpPlatformHandler's at `:336-349` - `Fail` with the download URL. The `-WhatIf`
   rehearsal reports it and stops there too. The block's own comment (`:350-365`)
   argued for a warning because the section in `web.config` would be 500.19 without
   the module; that argument is about *where the rule is written*, not whether the
   module is required, and stays - the rule keeps being written through the
   configuration API.
2. `deploy-checks.ps1`: two checks. Static - the site's `rewrite/rules` holds
   `AssetManagerClientAddress`. Live - `GET /health` gains `seen_from`, the address
   `_client_addr()` returns for that very request (additive, `api.md`'s rule for
   `/health`), and the check asserts it is neither empty nor loopback when run from a
   machine that is not the server.
3. Connected Clients: where `_iis_host()` is not None and every row's address is in
   `_LOOPBACK_PEERS`, one footer line - "IIS is not forwarding addresses: install URL
   Rewrite and re-run tools\install-iis.ps1". Absent otherwise.

## Not in this ticket

- Any change to `_client_addr()`'s trust rule. The loopback-only condition is the whole
  security of it (its docstring) and this ticket does not touch it.
- A client-reported address as a fallback. An unauthenticated caller choosing what the
  System Log says about it is the failure #187's docstring names.

## Cascade

- `docs/reference/tooling.md:418` (`install-iis.ps1` section) and `:1572`
  (`deploy-checks.ps1`) - the refusal and the two checks.
- `docs/runbooks/iis-cutover.md` - the prerequisites list gains URL Rewrite as a
  requirement, not an option.
- `docs/reference/api.md:37` - `/health` row gains `seen_from`.
- `docs/reference/apps.md` Connected Clients bullet (`:92-93`) - the footer hint.
- `tools/deploy-checks.ps1` and `install-iis.ps1` are ASCII-only (repo trap); no
  em-dash or arrow in the new strings.

## Verification

- Step 0's answer recorded.
- `-WhatIf` run of `install-iis.ps1` on a machine without URL Rewrite ends in the
  refusal; with it, passes the step.
- `deploy-checks.ps1` from a laptop: `seen_from` is that laptop's address.
- `py -3.12 tools/gate.py` on the diff; `ast.parse()` on `server.py`, `server_gui.py`.
