<#
.SYNOPSIS
    Behaviour checks for the deployment helpers in _deploy.ps1 - the
    certificate decision install-iis.ps1 makes when it was given no source,
    what bind-cert.ps1 does the rebinding through, where update.ps1 takes its
    install directory from, which interpreter a source install's migrations
    are run with, and that URL Rewrite's rule reaches GET /health (#242).

.DESCRIPTION
    The fourth gate, run beside cascade-audit.py, server-checks.py and
    client-checks.py before package.ps1. It exits non-zero, so it gates a
    release the same way, and it changes nothing outside a scratch directory
    of its own.

    Why it exists: install-iis.ps1 stands up IIS and cannot be run by a gate,
    so everything the other three know about that script is a source fact -
    that a warning names two fingerprints, that an https probe goes through
    Invoke-PinnedRequest. A source check cannot see a boolean written the
    wrong way round, and the first-time-setup branch is the decision there
    whose wrong answer costs the most: every client pins ssl_cert.pem and
    fails closed against anything else (rule 1), so a re-run that regenerated
    over an existing certificate would strand the whole fleet in the middle of
    routine maintenance with nothing said at the time.

    So the three conditions live in Test-FirstTimeCertSetup in _deploy.ps1,
    which is the file every script here dot-sources, and this drives all four
    states over it with Get-BoundCertThumbprint stubbed and a staged
    InstallDir on disk. No IIS, no elevation, and by default no network: the
    one check that touches one is skipped rather than run without -ServerUrl,
    which is what keeps this the answer gate.py gets when it calls the script
    with none.

    PowerShell rather than Python because what is under test is PowerShell,
    and no test framework - Pester would be a dependency on every machine that
    runs a release gate, and the other three gates are stdlib-only for the
    same kind of reason (rule 13).

    .\deploy-checks.ps1
    .\deploy-checks.ps1 -ServerUrl https://asset-server:8081

.PARAMETER ServerUrl
    A deployed server to probe GET /health on, from a machine that is not
    the server - a laptop on the VPN, not asset-server itself, since the
    one thing this check can prove is whether URL Rewrite is forwarding the
    caller's own address rather than the loopback hop every request makes
    on the server. Optional: without it the live check is skipped rather
    than failed, which is what lets gate.py go on calling this script with
    no arguments at all.

.PARAMETER PinPath
    An ssl_cert.pem to pin the https probe against, the same as every other
    caller of Invoke-PinnedRequest. Optional; with no pin and a plain
    http:// -ServerUrl, or an https:// one with nothing to pin against, the
    request is made with default certificate validation.
#>
[CmdletBinding()]
param(
    [string] $ServerUrl,
    [string] $PinPath
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_deploy.ps1")

$script:Failures = @()
$script:Bound    = $null

# The stub: IIS is not here, and what the decision needs from it is one
# thumbprint or nothing. Defined after the dot-source so it shadows the real
# one, which reads IIS:\SslBindings and would throw on a machine without the
# WebAdministration provider - which is every machine this gate runs on.
function Get-BoundCertThumbprint {
    param([Parameter(Mandatory = $true)][string] $SiteName)
    return $script:Bound
}

# _deploy.ps1's header says the caller defines Fail, and its refusals call it
# - Get-DeployConfig's, and Resolve-ServerRunner's for an interpreter that is
# not there. In a script it prints and exits, which a gate cannot have, so
# here it throws and the check that drives that refusal catches it.
function Fail($m) { throw $m }

function Head($Message) {
    Write-Host ""
    Write-Host ("=== " + $Message + " ===")
}

function Assert($What, $Got, $Want) {
    if ($Got -eq $Want) {
        Write-Host ("  [OK]    " + $What)
    } else {
        Write-Host ("  [FAIL]  " + $What + " - got '" + $Got + "', wanted '" + $Want + "'")
        $script:Failures += $What
    }
}

function New-StageDir {
    $dir = Join-Path ([IO.Path]::GetTempPath()) ("deploy-checks-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    return $dir
}


# ---- the first-time-setup decision ----------------------------------------
Head "install-iis.ps1 generates a certificate only on a first-time setup"

$stage = New-StageDir
try {
    $site = "AssetManager"

    # Nothing to point at: the one run where "give a certificate source" is a
    # demand the operator cannot satisfy.
    $script:Bound = $null
    Assert "no pem, nothing bound, no source given - generates" `
        (Test-FirstTimeCertSetup -InstallDir $stage -SiteName $site) $true

    # A pem beside a site that has not been bound yet is still a file clients
    # may already hold, so it is still not a first-time setup.
    Set-Content -Path (Join-Path $stage "ssl_cert.pem") -Value "-----BEGIN CERTIFICATE-----" -Encoding ASCII
    Assert "a pem and nothing bound - refuses" `
        (Test-FirstTimeCertSetup -InstallDir $stage -SiteName $site) $false

    # Both: plainly an install that has a certificate.
    $script:Bound = "AABBCCDDEEFF00112233445566778899AABBCCDD"
    Assert "a pem and a binding - refuses" `
        (Test-FirstTimeCertSetup -InstallDir $stage -SiteName $site) $false

    # A site bound to a certificate whose pem somebody deleted is still an
    # install with a certificate. This is the leg a single condition would get
    # wrong, and the one that strands the fleet.
    Remove-Item (Join-Path $stage "ssl_cert.pem")
    Assert "no pem but a binding - refuses" `
        (Test-FirstTimeCertSetup -InstallDir $stage -SiteName $site) $false

    # An explicit source keeps its own meaning whatever is on disk: -SelfSigned
    # mints one now and warns about what it replaces, -CertThumbprint and
    # -PfxPath name one that already exists.
    $script:Bound = $null
    Assert "a source was given, on a machine with nothing on it - not this branch" `
        (Test-FirstTimeCertSetup -InstallDir $stage -SiteName $site -SourceGiven $true) $false
}
finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}


# ---- the decision is written down once ------------------------------------
Head "install-iis.ps1 asks that helper rather than carrying a copy"

$iis = Get-Content (Join-Path $PSScriptRoot "install-iis.ps1") -Raw

# The branch has to be the helper's, or the four states above are being
# asserted about code the script does not run.
Assert "the zero-source branch calls Test-FirstTimeCertSetup" `
    ($iis -match "Test-FirstTimeCertSetup") $true

# And it must not have kept a second copy of either condition beside the call:
# two spellings of one decision is what rule 10 exists to prevent, and this is
# the decision where the copies disagreeing costs every client.
$strayPem = ([regex]::Matches($iis, 'Test-Path \(Join-Path \$InstallDir "ssl_cert\.pem"\)')).Count
Assert "no second Test-Path for ssl_cert.pem in the script" $strayPem 0

$strayBound = ([regex]::Matches($iis, 'Get-BoundCertThumbprint')).Count
Assert "no second read of the binding in the script" $strayBound 0

# -WhatIf generates nothing: the generation sits inside ShouldProcess, so a
# rehearsal on a fresh machine describes a certificate rather than minting one
# and writing a key that the real run would then replace.
Assert "the generation is guarded by ShouldProcess" `
    ($iis -match "ShouldProcess\([\s\S]{0,160}?Generate a self-signed certificate") $true


# ---- URL Rewrite is refused, not warned about, and named where it writes --
Head "install-iis.ps1 refuses without URL Rewrite and names the rule it writes"

# Static, reusing $iis above - a source check for the reason every other
# install-iis.ps1 decision here is one: the script stands up IIS and cannot
# be run by a gate. #242's finding was that an absent module only warned and
# the install went on serving loopback addresses forever; this is the
# regression check for that, not a rehearsal of the live rule.
Assert "URL Rewrite absent is a Fail, not a Warn" `
    ($iis -match 'Fail "URL Rewrite is not installed') $true
Assert "the old warn-and-continue wording is gone" `
    ($iis -match 'Warn "URL Rewrite is not installed') $false

# And where it does write the rule, it is still named AssetManagerClientAddress
# and still filed under system.webServer/rewrite/rules - server.py's
# _client_addr() and server_gui.py's Connected Clients hint both assume that
# name is the one IIS is holding.
Assert "the rule name is AssetManagerClientAddress" `
    ($iis -match '\$ruleName = "AssetManagerClientAddress"') $true
Assert "it is written under system.webServer/rewrite/rules" `
    ($iis -match "rewrite/rules/rule\[@name='\`$ruleName'\]") $true


# ---- bind-cert.ps1 rebinds and does nothing else --------------------------
Head "bind-cert.ps1 goes through the shared helpers"

# Source checks, for the reason the group above is written the other way
# round: this script imports a certificate into LocalMachine\My and writes
# IIS:\SslBindings, neither of which a gate may do, and the one decision in it
# that could be driven - the four states over Test-FirstTimeCertSetup - is not
# this script's. What is asserted here is what a source read can see and what
# costs the most when it is wrong: which implementation does the work, and
# which facts this script is not allowed to invent.
$bind = Get-Content (Join-Path $PSScriptRoot "bind-cert.ps1") -Raw

Assert "it dot-sources _deploy.ps1" `
    ($bind -match '\.\s+\(Join-Path \$PSScriptRoot "_deploy\.ps1"\)') $true

# One implementation of "rebind", two callers. A second IIS:\SslBindings write
# is the worst kind of copy to let drift: update.ps1's reconcile and this
# script would then be two answers to one question about the same site.
Assert "the import goes through Import-CertPair" `
    ($bind -match "Import-CertPair") $true
Assert "the bind goes through Set-SiteCertificate" `
    ($bind -match "Set-SiteCertificate") $true
# The write verbs, not the name: the comment above the elevation check names
# that path as somewhere an ordinary account cannot reach, which is a reason
# and not a write.
Assert "it writes no IIS:\SslBindings entry of its own" `
    (([regex]::Matches($bind, '(New|Remove|Set)-Item[^\r\n]*IIS:\\SslBindings')).Count) 0

# iis.json is install-iis.ps1's record of what it bound, not an answer typed
# at one rebind. Reading it is the point; writing it would make a rebind look
# like an install afterwards, to update.ps1 and to the GUI banner alike.
Assert "it reads iis.json" ($bind -match "iis\.json") $true
Assert "and writes no JSON at all" `
    (([regex]::Matches($bind, 'Write-JsonFile')).Count) 0

# Elevation before the settings, install-iis.ps1's rule: an unelevated shell
# told about a missing installDir has been told something true that is not why
# it was never going to bind anything.
$elevateAt = $bind.IndexOf("WindowsBuiltInRole")
$resolveAt = $bind.IndexOf('Resolve-Setting "InstallDir"')
Assert "elevation is checked before the settings are resolved" `
    ($elevateAt -gt 0 -and $resolveAt -gt $elevateAt) $true

# Both numbers through the one function, so this script, the Server GUI, the
# client's first-contact prompt and update.ps1 all say the same thing about
# one certificate. Get-FileHash hashes the PEM's own text, which is a
# different number that looks equally plausible and matches none of them.
Assert "both fingerprints come from Get-CertFingerprint" `
    (([regex]::Matches($bind, 'Get-CertFingerprint')).Count -ge 2) $true
Assert "and none from Get-FileHash" `
    (([regex]::Matches($bind, 'Get-FileHash')).Count) 0

# The key is read here, on the machine it was generated on, and goes nowhere:
# the one file that must never travel (rule 1).
Assert "it names ssl_key.pem only as a local path to read" `
    ($bind -match 'Join-Path \$InstallDir "ssl_key\.pem"') $true

# -WhatIf binds nothing, which is the helpers' own ShouldProcess rather than a
# branch here - so what this asserts is that the script declares it at all.
Assert "it supports -WhatIf" `
    ($bind -match "SupportsShouldProcess = \`$true") $true


# ---- bind-port.ps1 moves the binding and leaves a way back ----------------
Head "bind-port.ps1 binds the new port before it takes the old one away"

# Source checks, for the reason the group above is: this script writes
# IIS:\SslBindings, adds a firewall rule and restarts an app pool, none of
# which a gate may do, and there is no decision in it that could be driven
# without an IIS to drive it against. What is asserted is what a source read
# can see and what costs the most when it is wrong - the order of the three
# steps that decide whether the fleet follows the move, and which facts this
# script is and is not allowed to write.
$port = Get-Content (Join-Path $PSScriptRoot "bind-port.ps1") -Raw

Assert "it dot-sources _deploy.ps1" `
    ($port -match '\.\s+\(Join-Path \$PSScriptRoot "_deploy\.ps1"\)') $true

# Elevation before the settings, install-iis.ps1's rule and bind-cert.ps1's:
# an unelevated shell told about a missing installDir has been told something
# true that is not why it was never going to move anything.
$elevateAtP = $port.IndexOf("WindowsBuiltInRole")
$resolveAtP = $port.IndexOf('Resolve-Setting "InstallDir"')
Assert "elevation is checked before the settings are resolved" `
    ($elevateAtP -gt 0 -and $resolveAtP -gt $elevateAtP) $true

# The whole of the ticket, and the one ordering whose reverse strands the
# fleet: the new binding goes up, the grace window runs with both ports
# answering while every online client records next_port off /health on the
# old one, and only then does the old binding come down. Asserted as three
# offsets rather than as the presence of each, because each of them on its
# own was already there in install-iis.ps1 - what is new here is the order.
$addAt    = $port.IndexOf("New-WebBinding")
$sleepAt  = $port.IndexOf("Start-Sleep -Seconds `$Grace")
$removeAt = $port.IndexOf("Remove-WebBinding")
Assert "the new binding is added" ($addAt -gt 0) $true
Assert "the grace window comes after it" ($sleepAt -gt $addAt) $true
Assert "and the old binding is removed only after that" `
    ($removeAt -gt $sleepAt) $true

# The wait is the parameter, never a literal. A number written into the sleep
# is a grace window -Grace cannot shorten for a fleet that is all online, and
# cannot lengthen for one that is not.
Assert "the wait is -Grace itself" ($sleepAt -gt 0) $true
Assert "and its default is 120 seconds" `
    ($port -match '\[int\] \$Grace = 120') $true

# Both JSON writes go through the one no-BOM helper, for trap six: every
# Python app here reads its config with a plain open()/json.load, which
# decodes a BOM as cp1252 and dies. Two of them and no more - a third write
# would be this script inventing a fact about the install. Counted at the
# start of a line, so the comment above the first call - which names the
# helper as where that trap is written down - is a reason and not a write,
# the same distinction the SslBindings assert above draws.
Assert "it writes server_config.json" ($port -match "server_config\.json") $true
Assert "and iis.json, which bind-cert.ps1 does not" ($port -match "iis\.json") $true
Assert "both through Write-JsonFile" `
    (([regex]::Matches($port, '(?m)^\s*Write-JsonFile')).Count) 2
# Read-modify-write on both, never a fresh object: server_config.json also
# holds ssl_enabled, and iis.json holds five keys this script does not know
# about. The read of each is what proves it.
Assert "server_config.json is read before it is written" `
    ($port -match 'Read-JsonFile \$srvCfgPath') $true
Assert "and iis.json is too" `
    ($port -match 'Read-JsonFile \$statePath') $true

# The certificate carried onto the new port is the one the old binding is
# presenting, read through the same function update.ps1's reconcile and
# bind-cert.ps1 ask - never out of ssl_cert.pem, which is a copy of that fact
# and not the fact itself once the two can drift.
Assert "the certificate comes from Get-BoundCertThumbprint" `
    ($port -match "Get-BoundCertThumbprint") $true
Assert "and never off ssl_cert.pem" `
    (([regex]::Matches($port, 'ssl_cert\.pem')).Count) 0

# Every step is a ShouldProcess, so -WhatIf prints all seven and changes
# nothing. Declared at all is what a source read can see; the count is what
# stops a step being added outside one.
Assert "it supports -WhatIf" `
    ($port -match "SupportsShouldProcess = \`$true") $true
Assert "and every step is inside a ShouldProcess" `
    (([regex]::Matches($port, '\$PSCmdlet\.ShouldProcess')).Count -ge 6) $true


# ---- update.ps1 knows which install it is part of -------------------------
Head "update.ps1 takes its install directory from where it is installed"

$stage = New-StageDir
try {
    $tools   = Join-Path $stage "tools"
    $markers = @("installed.json", "server_config.json")
    New-Item -ItemType Directory -Path $tools | Out-Null

    # A tools\ directory with nothing beside it is not an install. This is
    # the answer that keeps the refusal: -Package carried to a machine by hand
    # is still asked for a -TargetDir rather than handed a guess.
    Assert "a tools\ with no install around it - no answer" `
        (Resolve-InstallFromTools $tools $markers) $null

    # installed.json is update.ps1's own record, so an install it has already
    # updated once answers on that alone.
    Set-Content -Path (Join-Path $stage "installed.json") -Value "{}" -Encoding ASCII
    Assert "installed.json beside it - the install directory" `
        (Resolve-InstallFromTools $tools $markers) $stage

    # And a never-updated install has no state file at all, which is exactly
    # the machine this ticket was raised from: server_config.json is what
    # answers for it.
    Remove-Item (Join-Path $stage "installed.json")
    Set-Content -Path (Join-Path $stage "server_config.json") -Value "{}" -Encoding ASCII
    Assert "server_config.json alone - still the install directory" `
        (Resolve-InstallFromTools $tools $markers) $stage

    # The guard that matters: a checkout has a tools\ of its own, and one
    # that has ever run the server has a server_config.json in its root - so
    # the marker above answers there too and .git is the only thing that
    # separates the two. Wrong, this would point an update at a repo.
    New-Item -ItemType Directory -Path (Join-Path $stage ".git") | Out-Null
    Assert "a .git beside it - no answer, marker or not" `
        (Resolve-InstallFromTools $tools $markers) $null

    # A .git file rather than a directory is what a worktree and a submodule
    # carry, and it is the same checkout either way.
    Remove-Item (Join-Path $stage ".git") -Recurse
    Set-Content -Path (Join-Path $stage ".git") -Value "gitdir: ../x" -Encoding ASCII
    Assert "a .git file rather than a directory - no answer" `
        (Resolve-InstallFromTools $tools $markers) $null

    Assert "no tools directory at all - no answer" `
        (Resolve-InstallFromTools "" $markers) $null
}
finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}


# ---- and asks for it rather than deriving one of its own ------------------
Head "update.ps1 asks that helper rather than carrying a copy"

# Source, for the reason the bind-cert.ps1 group is: this script stops an app
# pool, overwrites an install and migrates a database, so no gate can run it.
$upd = Get-Content (Join-Path $PSScriptRoot "update.ps1") -Raw

Assert "it resolves the install through Resolve-InstallFromTools" `
    ($upd -match "Resolve-InstallFromTools") $true

# Named by the variable, so the state file's own name stays written down once
# in the script that writes it.
Assert "and hands it its own state file as a marker" `
    ($upd -match 'Resolve-InstallFromTools \$PSScriptRoot @\(\$StateFile') $true

# No second derivation beside the call: -TargetDir and installDir still win,
# and a second spelling of "the install this script is in" is what would
# disagree with the helper's guards.
Assert "no other Split-Path of its own script root" `
    (([regex]::Matches($upd, 'Split-Path -Parent \$PSScriptRoot')).Count) 0

# The refusal stays for a tools\ sitting anywhere else, which is the
# first-install case the runbooks answer with -Package.
Assert "and still refuses when nothing answered" `
    ($upd -match 'No TargetDir\. Pass -TargetDir') $true

# ---- a source install's interpreter is resolved before it is invoked ------
Head "Resolve-ServerRunner hands back a full path, never a bare name"

# The other half of the same rule vendor.ps1 keeps, and the reason it is here
# rather than in a source check: the callers invoke a runner's File
# property,
# so the name is decided in this helper and invoked somewhere else entirely,
# and a source read at either end sees nothing wrong. update.ps1 reaches that
# & after it has stopped the app pool and copied the database aside, so a
# "python" that is not on PATH was a terminating CommandNotFoundException on
# a server that is down, with no rollback and nothing naming pythonExe.
$stage = New-StageDir
$prevPath = $env:PATH
try {
    Set-Content -Path (Join-Path $stage "run_server.py") -Value "" -Encoding ASCII
    $sys = Join-Path $env:SystemRoot "System32"
    $cmd = Join-Path $sys "cmd.exe"

    # PATH is narrowed to one directory so what resolves here is decided by
    # this check rather than by whatever the machine running it has installed.
    $env:PATH = $sys

    $r = Resolve-ServerRunner $stage "cmd.exe"
    Assert "a source install is the source engine" $r.Kind "source"
    Assert "and a bare name on PATH comes back as a full path" $r.File $cmd

    $r = Resolve-ServerRunner $stage $cmd
    Assert "a full path comes back as itself" $r.File $cmd

    # The case asset-server was in: no deploy.json, so no pythonExe, and no
    # python on the app pool's PATH either.
    $msg = ""
    try { Resolve-ServerRunner $stage "no-such-python.exe" | Out-Null }
    catch { $msg = "$_" }
    Assert "a name that resolves to nothing refuses" ($msg.Length -gt 0) $true
    Assert "and the refusal names the setting that answers it" `
        ($msg -match "pythonExe") $true

    # An exe install needs no interpreter at all, so an unresolvable one must
    # not refuse there - the exe branch answers before the question is asked.
    Set-Content -Path (Join-Path $stage "AssetServer.exe") -Value "" -Encoding ASCII
    $r = Resolve-ServerRunner $stage "no-such-python.exe"
    Assert "an exe install is unaffected" $r.Kind "exe"
    Assert "and runs the exe beside it" $r.File (Join-Path $stage "AssetServer.exe")
}
finally {
    $env:PATH = $prevPath
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}


# ---- the forwarded address reaches GET /health, from off the server ------
Head "GET /health's seen_from is the caller's own address, not the server's"

# Live, and the only check in this file that touches a network - #242's own
# deployment half cannot be proven any other way. _client_addr() trusts the
# forwarded header only from the loopback peer HttpPlatformHandler proxies
# every request through, so the one honest read of "is IIS forwarding it" is
# a request that actually arrived through IIS from somewhere else. Skipped
# rather than failed with no -ServerUrl, so gate.py's own no-argument run
# stays true to this file's docstring.
if (-not $ServerUrl) {
    Write-Host "  [SKIP]  GET /health seen_from - no -ServerUrl given"
} else {
    $healthUrl = $ServerUrl.TrimEnd("/") + "/health"
    $resp = Invoke-PinnedRequest -Url $healthUrl -PinPath $PinPath -TimeoutSec 10
    if ($resp.StatusCode -ne 200) {
        Write-Host ("  [FAIL]  GET " + $healthUrl + " did not answer: " + $resp.Error)
        $script:Failures += "GET /health did not answer"
    } else {
        $seenFrom = $null
        try { $seenFrom = (ConvertFrom-Json $resp.Content).seen_from } catch { }
        Assert "seen_from is present" ([string]::IsNullOrEmpty($seenFrom)) $false
        $loopbackPeers = @("127.0.0.1", "::1", "::ffff:127.0.0.1")
        Assert "seen_from is not a loopback address" `
            ($loopbackPeers -contains $seenFrom) $false
    }
}


Write-Host ""
Write-Host "=================================================================="
if ($script:Failures.Count -gt 0) {
    Write-Host ("" + $script:Failures.Count + " FAIL(S)")
    foreach ($f in $script:Failures) { Write-Host ("  FAIL: " + $f) }
    exit 1
}
Write-Host "all checks passed"
exit 0
