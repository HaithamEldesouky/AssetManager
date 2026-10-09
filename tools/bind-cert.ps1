<#
.SYNOPSIS
    Rebind the Asset Manager IIS site to the certificate ssl_cert.pem names.

.DESCRIPTION
    Imports <InstallDir>\ssl_cert.pem and ssl_key.pem into
    Cert:\LocalMachine\My where that certificate is not already there with its
    key, then binds the site's https port to it, and prints the fingerprint of
    what was bound before and of what is bound now.

    ssl_cert.pem is the source of truth and the binding is corrected to it,
    never the reverse: that file is what GET /cert serves and what every client
    has already pinned (rule 1), so a rebind the other way round would strand
    the fleet rather than repair it.

    This is the elevated half of the console's cutover (C4, ADR-0020). Under
    IIS the server runs as the app pool identity and is not an administrator,
    so it cannot rebind in process and has to spawn something that can. The
    obvious candidate, install-iis.ps1, is a full site install - it creates the
    site and the app pool, rewrites web.config, re-grants ACLs,
    read-modify-writes server_config.json and asks questions on an interactive
    run - which is a pile of side effects nobody asked for when the job is to
    swap a certificate. update.ps1 does not call this either: it already runs
    elevated, so it calls the same two helpers in process.

    Writes no iis.json. That file is install-iis.ps1's record of what it bound,
    not an answer typed at one rebind, so this reads it and leaves it alone -
    the same word update.ps1 takes it at.

.PARAMETER InstallDir
    The install directory: where ssl_cert.pem, ssl_key.pem and iis.json live.
    Defaults to installDir in deploy.json.

.PARAMETER SiteName
    The IIS site to rebind. Defaults to the site iis.json records, which is
    what install-iis.ps1 actually bound. Passing it wins over that file, for a
    machine whose site was renamed in IIS Manager afterwards.

.PARAMETER CertPath
    The certificate to bind. Defaults to <InstallDir>\ssl_cert.pem.

.PARAMETER KeyPath
    Its private key. Defaults to <InstallDir>\ssl_key.pem. Never travels: it is
    read here, on the machine it was generated on, and nowhere else.

.PARAMETER ConfigPath
    A deploy.json elsewhere. See tools/deploy.example.json.

.EXAMPLE
    .\bind-cert.ps1 -InstallDir C:\AssetManager

.EXAMPLE
    .\bind-cert.ps1 -WhatIf

    Prints what it would import and bind, and binds nothing.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Not Mandatory: may come from deploy.json instead, checked below.
    [string] $InstallDir,
    [string] $SiteName,
    [string] $CertPath,
    [string] $KeyPath,
    [string] $ConfigPath
)

$ErrorActionPreference = "Stop"

function Info ($m) { Write-Host "  $m" }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

# Elevation first, for install-iis.ps1's reason: the guards under it are only
# worth reading on a run that could have worked, and an unelevated shell told
# about a missing InstallDir has been told something true that is not why it was
# never going to bind anything. Both of the helpers below write to
# LocalMachine\My and IIS:\SslBindings, neither of which an ordinary account
# reaches.
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail "Run this from an elevated PowerShell prompt." }

$InstallDir = Resolve-Setting "InstallDir" $InstallDir $null "installDir"
if (-not $InstallDir) {
    Fail "No InstallDir. Pass -InstallDir, or set installDir in deploy.json."
}
if (-not (Test-Path $InstallDir)) { Fail "No such directory: $InstallDir" }

if (-not $CertPath) { $CertPath = Join-Path $InstallDir "ssl_cert.pem" }
if (-not $KeyPath)  { $KeyPath  = Join-Path $InstallDir "ssl_key.pem" }
if (-not (Test-Path $CertPath)) { Fail "No certificate at $CertPath." }
if (-not (Test-Path $KeyPath))  { Fail "No private key at $KeyPath." }

# The site comes from the record install-iis.ps1 left of what it bound, which
# is the same file update.ps1 resolves its host from and server.py's _iis_host
# reads for the banner. An unreadable one is a reason to say so and stop rather
# than to guess at a site name: binding the wrong site is a healthy server
# presenting an unchanged certificate while this run reports success.
$statePath = Join-Path $InstallDir "iis.json"
$state = $null
$stateUnreadable = $false
try { $state = Read-JsonFile $statePath } catch { $stateUnreadable = $true }
if (-not $SiteName) {
    if ($stateUnreadable) {
        Fail "$statePath is not JSON. Pass -SiteName to say which site serves this install."
    }
    if (-not $state -or -not $state.site) {
        Fail ("No site recorded in $statePath. This install may not be hosted " +
              "by IIS at all - pass -SiteName if it is.")
    }
    $SiteName = $state.site
}

# The app pool out of the same record, for the recycle at the end. Not a
# refusal when it is missing: an install whose iis.json predates the key still
# has a binding to correct, and the whole of what a missing name costs is a
# restart done by hand.
$appPool = ""
if ($state -and $state.app_pool) { $appPool = "$($state.app_pool)".Trim() }

Step "Rebinding $SiteName"
Info "install dir  $InstallDir"
Info "certificate  $CertPath"

Import-Module WebAdministration -ErrorAction SilentlyContinue
if (-not (Get-Website -Name $SiteName -ErrorAction SilentlyContinue)) {
    Fail "IIS has no site called $SiteName."
}

# Both sides through Get-CertFingerprint, so what is printed here is the same
# number the Server GUI shows, the client's first-contact prompt shows and
# update.ps1 prints - and never a thumbprint, which is a different hash of the
# same certificate and reads equally plausibly against any of them. The
# outgoing one is read off the binding rather than off any file: what is being
# replaced is what IIS is actually presenting.
$before = Get-BoundCertThumbprint -SiteName $SiteName
$beforeFp = "(nothing bound)"
if ($before) {
    $old = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $before }
    if ($old) { $beforeFp = Get-CertFingerprint -Der $old.RawData }
    else { $beforeFp = "(bound thumbprint $before is not in LocalMachine\My)" }
}
$afterFp = Get-CertFingerprint -Path $CertPath

Info "bound now    $beforeFp"
Info "binding to   $afterFp"
if ($before -and $beforeFp -eq $afterFp) {
    Info "Already bound to this certificate. Nothing to do."
    exit 0
}

# Every client that pinned the outgoing certificate fails closed against this
# one (rule 1), the hourly GET /cert refresh included, so this line is what the
# operator checks the fleet against before it happens.
Warn "Every client still holding $beforeFp will fail closed until it holds the new one."

$thumb = Import-CertPair -CertPath $CertPath -KeyPath $KeyPath
Info "thumbprint   $thumb"
Set-SiteCertificate -SiteName $SiteName -Thumbprint $thumb

# A rebind and a process that re-reads its files are one act, which is why the
# recycle is here rather than left to the caller. The server behind this site
# read ssl_cert.pem at startup: rebinding without cycling the pool leaves the
# new certificate at the edge over a process still holding the outgoing pair,
# and GET /cert - the one channel a client refreshes over - goes on serving the
# file that is no longer bound. bind-port.ps1 ends on the same call for the
# same reason. update.ps1 does not come through here; it cycles the pool itself.
if (-not $appPool) {
    Warn "no app pool recorded in $statePath - recycle it by hand, or the"
    Warn "process goes on serving from the certificate it read at startup"
} elseif ($PSCmdlet.ShouldProcess($appPool, "Restart app pool")) {
    Restart-WebAppPool -Name $appPool
    Info "$appPool restarted"
}

if ($WhatIfPreference) {
    Write-Host "`n[i] -WhatIf: nothing was imported and nothing was bound." -ForegroundColor Cyan
} else {
    Write-Host "`n[OK] $SiteName is bound to $afterFp" -ForegroundColor Green
}
