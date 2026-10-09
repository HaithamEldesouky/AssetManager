<#
.SYNOPSIS
    Move the Asset Manager IIS site onto a new port, with a grace window.

.DESCRIPTION
    Under IIS the port this install is served on is the site binding, so
    changing the number in server_config.json applies nothing on its own: the
    site goes on answering where it was bound and the two facts drift. This
    script is what moves the binding, in seven idempotent steps - the port
    recorded in server_config.json, an https binding on the new port beside
    the old one carrying the same certificate, a firewall rule for it,
    iis.json's own record, a pool restart so the process re-reads PORT, a
    grace window with both ports answering, and then the old binding removed.

    The grace window is the whole shape of it. While the old binding is still
    up, /health on the old port advertises the saved number as next_port and
    every online client records it on its 15s tick; when the old binding goes,
    each of them falls back to what it recorded, then to last_known_port. A
    move that took the old port away first would strand every client that had
    not been told, which is the same failure a certificate cutover has and the
    reason that one is two phases (ADR-0020).

    This is the elevated half of the console's Change Host / Port (ADR-0021),
    and it is a script of its own for bind-cert.ps1's reasons. Under IIS the
    server runs as the app pool identity and is not an administrator, so it
    cannot touch a binding, a firewall rule or an app pool in process and has
    to spawn something that can. install-iis.ps1 would move the port too and
    would also recreate the site and the app pool, rewrite web.config,
    re-grant ACLs and ask questions on an interactive run - a pile of side
    effects nobody asked for when the job is to move one number - and it takes
    the old binding away in the same breath, so it has no grace window at all.

    Writes iis.json, where bind-cert.ps1 deliberately does not. That file is
    install-iis.ps1's record of what it bound, and a rebind is not a fact it
    records - but the port is: iis.json states the port, so a script that
    moves the binding and left that key alone would leave the record naming a
    port nothing serves, which is the file update.ps1 and the Server GUI both
    take at its word.

.PARAMETER InstallDir
    The install directory: where server_config.json and iis.json live.
    Defaults to installDir in deploy.json.

.PARAMETER Port
    The port to move to. Required.

.PARAMETER SiteName
    The IIS site to move. Defaults to the site iis.json records, which is what
    install-iis.ps1 actually bound. Passing it wins over that file, for a
    machine whose site was renamed in IIS Manager afterwards.

.PARAMETER Grace
    Seconds to leave the old binding answering beside the new one, so every
    online client has a tick in which to record next_port. Default 120, which
    is eight of the client's 15s ticks. Zero removes the old binding at once,
    which is a decision about the fleet rather than a shortcut.

.PARAMETER ConfigPath
    A deploy.json elsewhere. See tools/deploy.example.json.

.EXAMPLE
    .\bind-port.ps1 -InstallDir C:\AssetManager -Port 8443

.EXAMPLE
    .\bind-port.ps1 -Port 8443 -WhatIf

    Prints the seven steps and changes nothing.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Not Mandatory: may come from deploy.json instead, checked below.
    [string] $InstallDir,
    [Parameter(Mandatory = $true)][int] $Port,
    [string] $SiteName,
    [int] $Grace = 120,
    [string] $ConfigPath
)

$ErrorActionPreference = "Stop"

function Info ($m) { Write-Host "  $m" }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

# Elevation first, for bind-cert.ps1's reason, which is install-iis.ps1's: the
# guards under it are only worth reading on a run that could have worked, and
# an unelevated shell told about a missing InstallDir has been told something
# true that is not why it was never going to move anything. Every write below
# - IIS:\SslBindings, the site's bindings, the firewall and the app pool - is
# somewhere an ordinary account does not reach.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "Run this from an elevated PowerShell prompt." }

if ($Port -lt 1 -or $Port -gt 65535) {
    Fail "Port must be between 1 and 65535."
}
if ($Grace -lt 0) { Fail "Grace cannot be negative." }

$InstallDir = Resolve-Setting "InstallDir" $InstallDir $null "installDir"
if (-not $InstallDir) {
    Fail "No InstallDir. Pass -InstallDir, or set installDir in deploy.json."
}
if (-not (Test-Path $InstallDir)) { Fail "No such directory: $InstallDir" }

# The site and the pool come from the record install-iis.ps1 left of what it
# bound, the same file bind-cert.ps1 resolves its site from and server.py's
# _iis_host reads for the banner. An unreadable one is a reason to say so and
# stop rather than to guess: moving the wrong site's binding is a healthy
# server on its old port while this run reports success.
$statePath = Join-Path $InstallDir "iis.json"
$state = $null
try { $state = Read-JsonFile $statePath }
catch { Fail "$statePath is not JSON. Pass -SiteName to say which site serves this install." }
if (-not $state) {
    Fail ("No $statePath. This install may not be hosted by IIS at all - " +
          "pass -SiteName if it is.")
}
if (-not $SiteName) {
    if (-not $state.site) {
        Fail ("No site recorded in $statePath. This install may not be hosted " +
              "by IIS at all - pass -SiteName if it is.")
    }
    $SiteName = $state.site
}
$appPool = $state.app_pool

Step "Moving $SiteName to port $Port"
Info "install dir  $InstallDir"

Import-Module WebAdministration -ErrorAction SilentlyContinue
if (-not (Get-Website -Name $SiteName -ErrorAction SilentlyContinue)) {
    Fail "IIS has no site called $SiteName."
}

# What the site is bound to now, read off IIS rather than out of iis.json: that
# file is a record and this is the fact. The old port is whichever https
# binding is not the new one, so a re-run after an interrupted move - where
# both bindings are already up - finds nothing to add and still has an old one
# to take away.
$httpsPorts = @()
foreach ($b in @(Get-WebBinding -Name $SiteName -Protocol https -ErrorAction SilentlyContinue)) {
    if ($b.bindingInformation -match '^[^:]*:(\d+):') { $httpsPorts += [int]$Matches[1] }
}
if (-not $httpsPorts) { Fail "Site $SiteName has no https binding to move." }
$oldPorts = @($httpsPorts | Where-Object { $_ -ne $Port })
$hasNew = ($httpsPorts -contains $Port)
if (-not $oldPorts -and $hasNew) {
    Info "Already bound to port $Port and to nothing else. Nothing to do."
    exit 0
}
Info "bound now    $($httpsPorts -join ', ')"
Info "moving to    $Port"

# Read before anything is added, so this is the certificate the old binding is
# presenting and not whichever https binding a resumed run happens to enumerate
# first. Through the one implementation both this script and update.ps1's
# reconcile ask, for bind-cert.ps1's reason.
$thumb = Get-BoundCertThumbprint -SiteName $SiteName
if (-not $thumb) {
    Fail ("Nothing is bound to $SiteName's https port, so there is no " +
          "certificate to carry to $Port. Run bind-cert.ps1 first.")
}
Info "certificate  $thumb"

# -- 1. server_config.json ------------------------------------------------------------
Step "1/7  Recording port $Port in server_config.json"

$srvCfgPath = Join-Path $InstallDir "server_config.json"
if ($PSCmdlet.ShouldProcess($srvCfgPath, "Record port $Port")) {
    # Read-modify-write, never overwrite, for install-iis.ps1's reason: this
    # file also holds ssl_enabled, and replacing it with a fresh one-key object
    # turns HTTPS off on the next restart with both cert files still on disk,
    # so nothing looks wrong until a client fails to verify.
    $srvCfg = @{}
    $readable = $true
    try {
        $existingCfg = Read-JsonFile $srvCfgPath
        if ($existingCfg) {
            $existingCfg.PSObject.Properties |
                ForEach-Object { $srvCfg[$_.Name] = $_.Value }
        }
    } catch {
        $readable = $false
        Warn "could not read $srvCfgPath ($($_.Exception.Message))"
        Warn "leaving it alone rather than overwriting it - repair it and set port to $Port,"
        Warn "or the Server GUI will probe a port IIS does not serve"
    }
    if ($readable) {
        $srvCfg["port"] = $Port
        # No-BOM UTF-8, because server.py reads this file with a plain
        # open()/json.load - see Write-JsonFile in _deploy.ps1 for the trap.
        Write-JsonFile $srvCfgPath $srvCfg
        Info "$srvCfgPath (port $Port)"
    }
}

# -- 2. The new binding, beside the old one ------------------------------------------------------------
Step "2/7  Binding $SiteName on port $Port beside port $($oldPorts -join ', ')"

if ($PSCmdlet.ShouldProcess("${SiteName}:$Port", "Add https binding and SSL certificate")) {
    if ($hasNew) {
        Info "https binding on $Port already present"
    } else {
        New-WebBinding -Name $SiteName -Protocol https -Port $Port
        Info "https binding added"
    }
    $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $thumb }
    if (-not $cert) {
        Fail "No certificate with thumbprint $thumb in LocalMachine\My."
    }
    # Not through Set-SiteCertificate: that one resolves the port off the
    # site's first https binding, which during this move is ambiguous by
    # design. The port is the argument here, so it is named.
    $existing = Get-Item "IIS:\SslBindings\0.0.0.0!$Port" -ErrorAction SilentlyContinue
    if ($existing) { Remove-Item "IIS:\SslBindings\0.0.0.0!$Port" -Force }
    New-Item -Path "IIS:\SslBindings\0.0.0.0!$Port" -Value $cert | Out-Null
    Info "certificate $($thumb.Substring(0,12))... bound to 0.0.0.0:$Port"
}

# -- 3. Firewall ------------------------------------------------------------
Step "3/7  Firewall rule for port $Port"

# The same rule shape install-iis.ps1 writes, so an install and a move leave
# one kind of rule behind rather than two. The old port's rule is left alone:
# it is what the grace window below is served through, and taking it away is
# not what was asked for.
$ruleName = "Asset Manager IIS ($Port)"
if ($PSCmdlet.ShouldProcess($ruleName, "Create inbound allow rule")) {
    if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
        Info "rule already present"
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port | Out-Null
        Info "created"
    }
}

# -- 4. iis.json ------------------------------------------------------------
Step "4/7  Recording port $Port in iis.json"

if ($PSCmdlet.ShouldProcess($statePath, "Record port $Port")) {
    # Read-modify-write, for server_config.json's reason: every other key here
    # is install-iis.ps1's record of what it bound, and this script knows one
    # of them. Written no-BOM through the same helper.
    $rec = @{}
    $state.PSObject.Properties | ForEach-Object { $rec[$_.Name] = $_.Value }
    $rec["port"] = $Port
    Write-JsonFile $statePath $rec
    Info "$statePath (port $Port)"
}

# -- 5. The pool ------------------------------------------------------------
Step "5/7  Restarting the app pool"

# So the process re-reads PORT out of server_config.json and /health reports
# the new number. HTTP_PLATFORM_PORT is IIS's own loopback port for the hop
# into this process and does not change with the site binding, so nothing the
# handler passes is affected by any of the above.
if (-not $appPool) {
    Warn "no app pool recorded in $statePath - restart it by hand, or the"
    Warn "process goes on reporting the old port from /health"
} elseif ($PSCmdlet.ShouldProcess($appPool, "Restart app pool")) {
    Restart-WebAppPool -Name $appPool
    Info "$appPool restarted"
}

# -- 6. The grace window ------------------------------------------------------------
Step "6/7  Leaving port $($oldPorts -join ', ') answering for ${Grace}s"

# This is the window the clients are moved in, and the reason this script is
# not two lines. /health on the old port advertises the saved number as
# next_port, and every online client records it on its 15s tick; the old
# binding is what keeps that channel open long enough for them to.
if ($PSCmdlet.ShouldProcess("port $($oldPorts -join ', ')", "Keep answering for ${Grace}s")) {
    if ($Grace -gt 0) {
        Info "every online client records next_port within one 15s tick"
        Start-Sleep -Seconds $Grace
    } else {
        Warn "no grace window: a client that has not recorded next_port falls"
        Warn "back to last_known_port, and one switched off through this move"
        Warn "needs its config.json corrected by hand"
    }
}

# -- 7. The old binding goes ------------------------------------------------------------
Step "7/7  Removing the old binding"

foreach ($old in $oldPorts) {
    if ($PSCmdlet.ShouldProcess("${SiteName}:$old", "Remove https binding and SSL certificate")) {
        $ssl = Get-Item "IIS:\SslBindings\0.0.0.0!$old" -ErrorAction SilentlyContinue
        if ($ssl) { Remove-Item "IIS:\SslBindings\0.0.0.0!$old" -Force }
        Remove-WebBinding -Name $SiteName -Protocol https -Port $old -ErrorAction SilentlyContinue
        Info "port $old removed"
    }
}

if ($WhatIfPreference) {
    Write-Host "`n[i] -WhatIf: nothing was written, bound or removed." -ForegroundColor Cyan
} else {
    Write-Host "`n[OK] $SiteName moved from $($oldPorts -join ', ') to $Port" -ForegroundColor Green
    Write-Host "Next: point new clients at https://$($env:COMPUTERNAME):$Port" -ForegroundColor Cyan
}
