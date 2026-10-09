<#
.SYNOPSIS
    Launch a local dev instance of the server, the Storekeeper and one Notifier
    per engineer, so behaviour can be tested on one machine.

.DESCRIPTION
    Each app resolves config.json, assets.db and ssl_cert.pem next to its own
    source file, so running all three straight out of the repo root would make
    them share - and fight over - a single config.json. This script stages a
    directory per app under .dev\, copies the sources in fresh on every run,
    writes the config each app expects, and starts them.

    Re-run it after editing a source file: the copy is what runs, so an edit
    only takes effect on the next launch. Stop everything with -Stop.

    Consoles are hidden and stdout/stderr go to dev.out.log / dev.err.log in
    each app's directory - a traceback would otherwise vanish with the window.

.EXAMPLE
    .\tools\dev-run.ps1
    Server GUI plus Storekeeper plus one Notifier on http://127.0.0.1:8081.

.EXAMPLE
    .\tools\dev-run.ps1 -Https -Engineers "Brian Dawson","Carol Evans" -Reset
    Fresh database, self-signed HTTPS, two Notifiers.

.EXAMPLE
    .\tools\dev-run.ps1 -Stop
#>
[CmdletBinding()]
param(
    # Port the dev server listens on.
    [int] $Port = 8081,

    # One Notifier is started per name. The name must be an engineer the server
    # knows, since the Notifier polls /pending/<name>.
    [string[]] $Engineers = @("Alice Carter"),

    # Admin password for the dev instance. Only written when admin_config.json
    # does not exist yet, so a password changed from the Server GUI survives a
    # relaunch. Use -Reset to go back to this one.
    [string] $AdminPassword = "admin",

    # Where the staged app directories live. Defaults to .dev\ in the repo.
    [string] $DevDir,

    [string] $PythonExe,

    # Serve HTTPS with a self-signed certificate, generated once into the
    # server directory and copied to each client as its trust anchor.
    [switch] $Https,

    # Run the server as "server.py serve" instead of opening the Tkinter GUI.
    [switch] $Headless,

    [switch] $ServerOnly,

    # Delete the staged tree first: fresh database, members, configs, password.
    [switch] $Reset,

    [switch] $Stop
)

$ErrorActionPreference = "Stop"

function Step($m) { Write-Host ""; Write-Host ("==> " + $m) -ForegroundColor Cyan }
function Info($m) { Write-Host ("    " + $m) }
function Fail($m) { Write-Host ("ERROR: " + $m) -ForegroundColor Red; exit 1 }

# Dot-sourced for Read-JsonFile and Write-JsonFile alone - there is no
# deploy.json in a dev run and nothing here calls Initialize-DeploySettings. The
# no-BOM write was spelled out here as well until the two copies were folded
# into one; Info and Fail above are what that file asks its callers to define.
. (Join-Path $PSScriptRoot "_deploy.ps1")

$Root = Split-Path -Parent $PSScriptRoot
if (-not $DevDir) { $DevDir = Join-Path $Root ".dev" }
$PidFile = Join-Path $DevDir "dev-pids.json"

# ---------------------------------------------------------------- stop / reset

function Stop-Dev {
    if (-not (Test-Path $PidFile)) {
        Info "no dev-pids.json - nothing was started by this script"
        return
    }
    # The ForEach-Object is not decoration: Windows PowerShell 5.1 hands a
    # JSON array back from ConvertFrom-Json as ONE Object[] instead of
    # enumerating it, so @() wrapped it into a single element and the loop
    # below ran once with $r bound to every row at the same time. That
    # defeated the recycled-pid check just below - $r.ProcessId became an
    # array, and Stop-Process killed every recorded pid as long as any one
    # of them was python. PS 7 enumerates; this flattens both the same way,
    # and a one-row file still yields one row.
    $rows = @(Get-Content $PidFile -Raw | ConvertFrom-Json | ForEach-Object { $_ })
    foreach ($r in $rows) {
        $p = Get-Process -Id $r.ProcessId -ErrorAction SilentlyContinue
        # The name check guards against a recycled PID: killing whatever else
        # happens to hold that number would be worse than leaking a process.
        if ($p -and $p.ProcessName -like "python*") {
            # Tolerate the process exiting between the Get and the Stop.
            # $ErrorActionPreference is "Stop" here, so an ObjectNotFound
            # from a pid that died a moment ago is terminating: it used to
            # abandon every row below it and leave the pid file in place, so
            # one crashed app stranded the others and every later -Stop
            # aborted on the same dead pid.
            try {
                Stop-Process -InputObject $p -Force -ErrorAction Stop
                Info ("stopped " + $r.Label + " (pid " + $r.ProcessId + ")")
            } catch {
                Info ($r.Label + " (pid " + $r.ProcessId + ") exited before it could be stopped")
            }
        } else {
            Info ($r.Label + " (pid " + $r.ProcessId + ") already gone")
        }
    }
    Remove-Item $PidFile -Force
}

if ($Stop) {
    Step "Stopping the dev instance"
    Stop-Dev
    exit 0
}

# --------------------------------------------------------------- sanity checks

if ($Port -lt 1 -or $Port -gt 65535) { Fail "port must be between 1 and 65535" }

if (-not $PythonExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Fail "python is not on PATH - pass -PythonExe C:\path\to\python.exe" }
    $PythonExe = $cmd.Source
}
if (-not (Test-Path $PythonExe)) { Fail ("no such python: " + $PythonExe) }

foreach ($f in @("server.py", "storekeeper_app.py", "notifier_app.py")) {
    if (-not (Test-Path (Join-Path $Root $f))) { Fail ("missing " + $f + " in " + $Root) }
}

if ($Reset) {
    Step "Resetting the dev tree"
    Stop-Dev
    if (Test-Path $DevDir) { Remove-Item $DevDir -Recurse -Force }
    Info ("deleted " + $DevDir)
}

function Test-PortFree([int] $p) {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
    try { $listener.Start(); $listener.Stop(); return $true } catch { return $false }
}

if (-not (Test-PortFree $Port)) {
    Info ("something is already listening on 127.0.0.1:" + $Port)
    Info ("  Get-NetTCPConnection -LocalPort " + $Port + " -State Listen | Select-Object OwningProcess")
    Fail ("port " + $Port + " is in use - stop it, or pass a different -Port")
}

# ---------------------------------------------------------------------- helpers

function Get-PasswordHash([string] $s) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($s)) |
                 ForEach-Object { $_.ToString("x2") }) -join "")
    } finally { $sha.Dispose() }
}

function New-AppDir($name, $sourceFiles) {
    $dir = Join-Path $DevDir $name
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    foreach ($f in $sourceFiles) {
        Copy-Item (Join-Path $Root $f) (Join-Path $dir $f) -Force
    }
    return $dir
}

$Started = @()

function Start-App($label, $dir, $appArgs) {
    $p = Start-Process -FilePath $PythonExe -ArgumentList $appArgs `
                       -WorkingDirectory $dir `
                       -RedirectStandardOutput (Join-Path $dir "dev.out.log") `
                       -RedirectStandardError  (Join-Path $dir "dev.err.log") `
                       -WindowStyle Hidden -PassThru
    $script:Started += [pscustomobject]@{ Label = $label; ProcessId = $p.Id; Dir = $dir }
    Info ($label + " -> pid " + $p.Id + "   (" + $dir + ")")
}

function Wait-Listen([int] $p, [int] $seconds = 40) {
    for ($i = 0; $i -lt $seconds * 4; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        try { $client.Connect("127.0.0.1", $p); $client.Close(); return $true }
        catch { Start-Sleep -Milliseconds 250 }
        finally { $client.Dispose() }
    }
    return $false
}

$scheme    = if ($Https) { "https" } else { "http" }
$serverUrl = $scheme + "://127.0.0.1:" + $Port

# ----------------------------------------------------------------------- server

Step "Staging the server"
$srvDir = New-AppDir "server" @("server.py", "server_gui.py", "server_cert.py", "register_assets.py", "register_transactions.py", "register_engineers.py", "server_mail.py", "server_sync.py", "server_clients.py", "server_log.py", "server_archive.py", "server_lookup.py", "server_iis.py", "gui_assets.py", "gui_backup.py", "gui_clients.py", "gui_log.py", "gui_mail.py", "gui_proposals.py", "gui_records.py", "gui_settings.py", "gui_users.py", "ui_kit.py")
Copy-Item (Join-Path $Root "migrations") $srvDir -Recurse -Force

$adminCfg = Join-Path $srvDir "admin_config.json"
if (Test-Path $adminCfg) {
    Info "kept the existing admin_config.json (use -Reset to reset the password)"
} else {
    Write-JsonFile $adminCfg @{ password_hash = (Get-PasswordHash $AdminPassword); first_run = $false }
    Info ("admin password: " + $AdminPassword)
}

$certPath = Join-Path $srvDir "ssl_cert.pem"
$keyPath  = Join-Path $srvDir "ssl_key.pem"
if ($Https -and -not ((Test-Path $certPath) -and (Test-Path $keyPath))) {
    Info "generating a self-signed certificate for 127.0.0.1"
    & $PythonExe (Join-Path $PSScriptRoot "_devtools.py") "cert" $certPath $keyPath | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "certificate generation failed - is 'cryptography' installed?" }
}

# host/port/ssl are the launcher's business, so they are rewritten every run.
# Any other key already in the file is kept.
$srvCfgPath = Join-Path $srvDir "server_config.json"
$srvCfg = @{}
$existingSrvCfg = Read-JsonFile $srvCfgPath
if ($existingSrvCfg) {
    $existingSrvCfg.PSObject.Properties |
        ForEach-Object { $srvCfg[$_.Name] = $_.Value }
}
$srvCfg["host"] = "127.0.0.1"
$srvCfg["port"] = $Port
$srvCfg["ssl_enabled"] = [bool] $Https
Write-JsonFile $srvCfgPath $srvCfg

Step ("Starting the server on " + $serverUrl)
if ($Headless) { Start-App "server (headless)" $srvDir @("server.py", "serve") }
else           { Start-App "server (GUI)"      $srvDir @("server.py") }

if (-not (Wait-Listen $Port)) {
    Info ("check " + (Join-Path $srvDir "dev.err.log"))
    Fail ("the server never started listening on " + $Port)
}
Info "listening"

if (-not $Https) {
    # Only probed over plain HTTP: verifying a self-signed certificate from
    # PowerShell needs either a trust-store install or a check-skipping switch
    # that only exists in PowerShell 7, and the TCP wait above already proves
    # the listener is up.
    try {
        $h = Invoke-RestMethod ($serverUrl + "/health") -TimeoutSec 5
        $nxt = if ($h.next_port) { $h.next_port } else { "-" }
        Info ("health: port=" + $h.port + " next_port=" + $nxt + " records=" + $h.total)
    } catch {
        Info ("/health did not answer: " + $_.Exception.Message)
    }
}

$lookup = Join-Path $srvDir "asset_lookup.xlsx"
if (Test-Path $lookup) {
    Info "assets you can submit (a submission is refused for anything not in the lookup):"
    & $PythonExe (Join-Path $PSScriptRoot "_devtools.py") "lookup" $lookup 5
}

# ---------------------------------------------------------------------- clients

if (-not $ServerOnly) {
    Step "Staging and starting the clients"

    # Every module of ours a client imports, alongside it: each staged directory
    # is its own import root, so sys.path[0] is that directory and nothing else
    # of this repo is on the path. A name missing here is not a degraded run, it
    # is the app dying on its own import block - and with the console hidden,
    # Start-App still prints a pid, the pid still goes in dev-pids.json and this
    # script still ends on "Running". client_update.py was the one that proved
    # it: both clients have imported it at module level since it landed, and
    # neither has started here since. cascade-audit.py now derives this list
    # from what the apps actually import rather than trusting it to be kept.
    $ClientShared = @("common.py", "ui_kit.py", "client_update.py")
    # The Notifier's own two beside its app file: the Pending decisions
    # (#208) and the Remote Admin surface (#218). Not in $ClientShared -
    # the Storekeeper imports neither of them.
    $NotifierOwn = @("notifier_app.py", "notifier_pending.py",
                     "notifier_remote.py")

    # The Storekeeper's own beside its app file: the export (#219). Not in
    # $ClientShared for $NotifierOwn's reason - the Notifier does not import it.
    $StorekeeperOwn = @("storekeeper_app.py", "storekeeper_export.py", "storekeeper_bulk.py", "storekeeper_propose.py")

    $stkDir = New-AppDir "storekeeper" ($StorekeeperOwn + $ClientShared)
    Write-JsonFile (Join-Path $stkDir "config.json") @{ server_url = $serverUrl }
    if ($Https) { Copy-Item $certPath $stkDir -Force }
    Start-App "storekeeper" $stkDir @("storekeeper_app.py")

    foreach ($eng in $Engineers) {
        # One directory per engineer: two Notifiers in one directory would
        # overwrite each other's current_user and both poll the same member.
        $slug = ($eng -replace "[^A-Za-z0-9]+", "-").Trim("-").ToLower()
        $nDir = New-AppDir ("notifier-" + $slug) ($NotifierOwn + $ClientShared)
        Write-JsonFile (Join-Path $nDir "config.json") @{
            server_url     = $serverUrl
            current_user   = $eng
            poll_interval  = 5
            setup_complete = $true
        }
        if ($Https) { Copy-Item $certPath $nDir -Force }
        Start-App ("notifier: " + $eng) $nDir @("notifier_app.py")
    }
}

# ------------------------------------------------------------------------- done

Write-JsonFile $PidFile $Started

Step "Running"
Info ("server url : " + $serverUrl)
Info ("dev tree   : " + $DevDir)
Info ("logs       : " + (Join-Path $DevDir "<app>\dev.err.log"))
Info ("stop with  : .\tools\dev-run.ps1 -Stop")
Write-Host ""
