<#
.SYNOPSIS
    Install a specific packaged version onto a machine - upgrade or downgrade.

.DESCRIPTION
    Installs packages produced by tools/package.ps1. The order is deliberate:
    nothing destructive happens until every check has passed.

      1. verify the manifest hashes, so a truncated copy fails here rather than
         halfway through overwriting a live install
      2. refuse a package marked git_dirty unless -AllowDirty
      3. stop whatever is serving - the IIS app pool iis.json names, otherwise
         the AssetManagerServer service; where iis.json is missing or names a
         site IIS no longer has, and somebody is at the console, it asks which
         site rather than guessing (see Resolve-HostAppPool)
      4. copy the database (wherever db_path puts it), and its -wal and -shm
         files, into rollback\<old-version>\ - before anything is written
      5. migrate to the package's schema version, up or
         down, by calling server.py's migrate verb - as AssetServer.exe on an exe
         install, as `python run_server.py` on a source one
      6. copy every file the package will overwrite into rollback\<old-version>\,
         then write the new ones
      7. start the service or app pool again
      8. health-check /version and confirm it reports the version just
         installed; if it does not, put the previous files back automatically

    Step 8 is the point of the script: an update that leaves the server
    unreachable is worse than no update, and after a downgrade the old exes are
    the only build that still matches the migrated database.

    Step 4 is this script's own copy, and it is not the migration's. server.py
    writes a .bak-v* file only when it has a migration to run, and it returns
    early when the schema is already at target - which is the common case, so
    an update that changes no schema used to back up nothing at all while
    overwriting every exe under it.

    Step 8 never puts that copy back. The health check can fail minutes after
    the new build started serving, and every transaction recorded in between is
    real: restoring an older database would destroy them. The copy is there to
    be restored by hand, by someone who has looked.

    Migrations are run by server.py, not by this script, because PowerShell has
    no SQLite support - neither 5.1 nor 7 ships a provider and sqlite3.exe is
    absent on Windows. server.py already imports sqlite3.

    This script ships inside AssetManager-<version>.zip and is installed
    to <TargetDir>\tools\ with the rest of it, so the updater on a machine is
    always the one that shipped with the newest build installed there. That is
    not a chicken-and-egg: it is never needed to OBTAIN a package, only to apply
    one, and by then an install has already put it on the machine. It replaces
    itself as it runs - the copy in <TargetDir>\tools\ is one of the files the
    package overwrites - which is safe because PowerShell parses a script whole
    before executing a line of it, _deploy.ps1 is dot-sourced long before
    anything is written, and the outgoing copy goes into rollback\<old-version>\
    with every other replaced file.

.PARAMETER Version
    Version to install, e.g. 2.1.0. Resolves to AssetManager-<v>.zip - or
    AssetManager-<v>-source.zip, for a package built before the suffix was
    dropped, and for an exe package built before 061 - under
    <TargetDir>\dist\, or under -PackageDir where that is passed.

.PARAMETER Package
    Explicit path to a package zip, instead of -Version.

.PARAMETER TargetDir
    Install directory. Read from installDir in deploy.json when not passed,
    and failing that from this script's own location: the package installs it
    to <TargetDir>\tools\, so an updater that shipped with the release
    already knows which install it is part of. It is the same directory
    install-iis.ps1 configures, so one file describes it once.

.PARAMETER BaseUrl
    e.g. https://asset-server:8081 - enables the health check and auto-rollback.
    Read from baseUrl in deploy.json when not passed. Not derived from the port,
    deliberately: guessing the scheme wrong fails the health check and rolls back
    a perfectly good update.

.PARAMETER PackageDir
    Where to look for the package, instead of <TargetDir>\dist\. Passed here it
    is the only place looked: falling through to a directory the caller did not
    name would install a package they never pointed at.

    Pointed at a file rather than a directory it is the package itself and is
    read as -Package. A zip's own path is what an operator actually has in hand,
    and the two readings cannot both hold - a leaf is never a directory - so
    searching <zip>\<version>\ and <zip>\ beneath it could only ever refuse.

    Left off there is one place, and it is on the machine being updated -
    dist\ under the install directory. Drop the release there and run this. The
    four-place search that stood here existed for an updater carried to a machine
    by hand, which had to guess where the person carrying it had been standing;
    this script is installed to <TargetDir>\tools\ by the package itself, so the
    updater and the packages it applies are two parts of one install and there is
    nothing left to guess between.

    Either way the directory is looked at twice: <dir>\<version>\ first, then
    <dir> itself. package.ps1 writes dist\<version>\ and that whole directory is
    the unit that gets carried to a machine, while a zip carried on its own lands
    beside it rather than in a subdirectory of its own. The line printed says
    which of the two answered.

    When neither shape holds the requested version and somebody is at the
    console, it lists each place it looked and what was there, then asks for a
    directory. An empty answer, or nobody to ask, keeps the refusal.

.PARAMETER PythonExe
    The interpreter to run run_server.py with on a source install. Ignored when
    AssetServer.exe is present. Read from pythonExe in deploy.json; defaults to
    whatever `python` resolves to.

.PARAMETER ConfigPath
    A JSON file supplying TargetDir, BaseUrl and PythonExe. Defaults to
    deploy.json next to this script, then deploy.json in the repo root. See
    tools/deploy.example.json. A parameter passed on the command line always
    wins over the file. Where the package is read from is not one of its keys
    any more - installDir settles that, being the directory dist\ sits under.
    See .PARAMETER PackageDir.

.EXAMPLE
    .\update.ps1 -Version 2.1.0                 # target and base url from deploy.json
.EXAMPLE
    .\update.ps1 -Version 2.1.0 -TargetDir C:\AssetManager -BaseUrl https://asset-server:8081
.EXAMPLE
    .\update.ps1 -Version 2.0.0 -TargetDir C:\AssetManager -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "ByVersion")] [string] $Version,
    [Parameter(Mandatory = $true, ParameterSetName = "ByPath")]    [string] $Package,
    # Not Mandatory: may come from deploy.json instead. Resolved and checked
    # below, before anything on the machine is touched.
    [string] $TargetDir,
    [string] $BaseUrl,
    [string] $PackageDir,
    [string] $PythonExe,
    [string] $ConfigPath,
    [switch] $AllowDirty,
    [switch] $SkipHealth
)

$ErrorActionPreference = "Stop"

$ServiceName = "AssetManagerServer"
$StateFile   = "installed.json"

function Info ($m) { Write-Host "  $m" }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

function Copy-Into ($src, $dest) {
    # Copy-Item does not create intermediate directories, and a package is not
    # flat: lib/ arrives several hundred files deep. Without this the write loop
    # fails on the first nested file and the rollback loop saves nothing.
    $dir = Split-Path -Parent $dest
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Copy-Item $src $dest -Force
}

function Format-ZipListing ($dir) {
    # What is actually in the directory that was looked in, as one line to
    # print. Printed either way: it is the whole of the evidence in the refusal
    # a run with nobody at it gets, and it is what makes the question
    # answerable in the run that asks.
    if (-not $dir) { $dir = "." }
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return "no such directory" }
    $names = @(Get-ChildItem -LiteralPath $dir -Filter *.zip | ForEach-Object { $_.Name })
    if ($names) { return ($names -join ", ") }
    return "no zips there"
}

function Compare-SemVer ($a, $b) {
    $pa = [int[]]($a -split '\.'); $pb = [int[]]($b -split '\.')
    for ($i = 0; $i -lt 3; $i++) {
        if ($pa[$i] -gt $pb[$i]) { return 1 }
        if ($pa[$i] -lt $pb[$i]) { return -1 }
    }
    return 0
}

function Resolve-HostAppPool ([string] $targetDir, [bool] $canPrompt) {
    <#
        Which process is serving this install: the name of the IIS app pool to
        cycle, or $null to cycle the AssetManagerServer service instead.

        iis.json is install-iis.ps1's record of what it configured, and it is
        the only thing on the machine that says this install is hosted by IIS.
        Absent - deleted by the rollback in docs/runbooks/iis-cutover.md, or
        never written because the cutover was finished by hand - this used to
        fall straight through to `sc.exe stop AssetManagerServer`, which on an
        IIS install stops nothing at all: the update then overwrites files
        under a running worker, and the health check reports the old version
        with nothing anywhere saying why. A site named in iis.json that IIS no
        longer has is the same failure by a different route.

        So where somebody is at the console and IIS has sites to offer, that is
        a question rather than a guess. The answer names a site and the pool is
        read off the site - two answers that have to agree is one question too
        many - and an empty answer means there is no IIS here and keeps the
        service. Nothing is written back: iis.json belongs to install-iis.ps1,
        and an answer recorded here would make a guess look like a configured
        fact, so the run points at that script instead.

        Where there is nobody to ask - a scheduled run, a redirected stdin,
        -WhatIf - or where IIS cannot be read at all, the recorded value stands
        exactly as it did before. The decision and the reason for it are
        printed either way: this function never fails, and the line it prints
        is the only warning a run that could not be asked ever gets.
    #>
    $iisPath  = Join-Path $targetDir "iis.json"
    $recorded = ""
    $site     = ""
    try {
        $iis = Read-JsonFile $iisPath
        if ($iis) {
            $recorded = "$($iis.app_pool)".Trim()
            $site     = "$($iis.site)".Trim()
        }
    } catch {
        # Unreadable says as little as absent, and ending the run here would be
        # ending it over a file that only decides which of two Stop calls to
        # make. The reason below then reads it as "records no app pool", which
        # is what an unreadable file amounts to here.
        Warn "could not read $iisPath ($($_.Exception.Message))"
    }

    # The site list is both the check and the offer, so IIS is read once.
    # Guarded rather than assumed: Import-Module WebAdministration already
    # happens on the app-pool path, but only once iis.json has said there is a
    # pool to cycle. Reaching it from here unguarded would make IIS support a
    # requirement of every update, including the service installs that are
    # most of them. An unelevated shell, a half-installed feature and a broken
    # module all arrive in the same catch and all mean the same thing here:
    # IIS cannot be asked, so nothing is verified and nothing is offered.
    $sites    = $null
    $sitesWhy = "no IIS PowerShell support on this machine"
    if (Get-Module -ListAvailable -Name WebAdministration) {
        try {
            Import-Module WebAdministration -ErrorAction Stop
            $sites = @(Get-Website)
        } catch {
            $sitesWhy = "IIS could not be read ($($_.Exception.Message))"
        }
    }
    $names = @($sites | ForEach-Object { $_.Name })

    $decided = if ($recorded) { "IIS app pool $recorded" } else { "Windows service $ServiceName" }

    if ($recorded -and $null -eq $sites) {
        # Recorded but unverifiable, so the record stands: IIS being
        # unreadable from this shell is not evidence that the pool is gone.
        Info "host      : $decided - from iis.json, unverified ($sitesWhy)"
        return $recorded
    }
    # An iis.json written before install-iis.ps1 recorded the site name carries
    # an app_pool and no site. There is nothing to check that against, so it is
    # taken at its word exactly as it was before this check existed.
    if ($recorded -and (-not $site -or $names -contains $site)) {
        Info "host      : $decided$(if ($site) { " (site $site)" }) - from iis.json"
        return $recorded
    }

    $reason =
        if (-not (Test-Path $iisPath)) { "there is no iis.json in $targetDir" }
        elseif (-not $recorded)        { "$iisPath records no app pool" }
        else { "iis.json names the site '$site', which IIS does not have" }

    $noAsk =
        if (-not $canPrompt)       { "nobody at this console to ask" }
        elseif ($null -eq $sites)  { $sitesWhy }
        elseif (-not $names.Count) { "IIS is installed here and has no sites" }
        else { "" }

    if ($noAsk) {
        # Today's behaviour, unchanged: the recorded pool where there is one,
        # the service where there is not. A question nobody can answer, or one
        # whose every answer IIS would reject, is not asked - it is printed.
        Info "host      : $decided - $reason, and $noAsk"
        return $recorded
    }

    Warn $reason
    Info "IIS on this machine has: $($names -join ', ')"
    while ($true) {
        $answer = (Read-Host "  Site serving this install (Enter for the $ServiceName service)").Trim()
        if (-not $answer) {
            Info "host      : Windows service $ServiceName - answered at the prompt"
            return $null
        }
        if ($names -notcontains $answer) {
            Warn "IIS has no site named '$answer'."
            continue
        }
        $pool = "$(($sites | Where-Object { $_.Name -eq $answer }).applicationPool)".Trim()
        if (-not $pool) {
            Warn "site '$answer' names no application pool."
            continue
        }
        Info "host      : IIS app pool $pool (site $answer) - answered at the prompt"
        Info "            iis.json is not written from here. Run install-iis.ps1 to record it."
        return $pool
    }
}

function Get-CertMismatch ([string] $certPath, [string] $siteName) {
    <#
        Local-only comparison between ssl_cert.pem - what GET /cert serves and
        what every client has pinned - and whatever certificate IIS actually
        has bound to $siteName's https port. No network call, so both the
        -WhatIf preview above and the live reconcile in the health-check step
        below can ask this same question and get the same answer, rather than
        each carrying its own copy of the comparison.

        $null when there is nothing to reconcile: no ssl_cert.pem, no site, no
        https binding on it (Get-BoundCertThumbprint's own $null cases), or a
        binding that already matches the file. Otherwise a hashtable naming
        both sides - FileFingerprint and BoundFingerprint, the same
        Get-CertFingerprint number update.ps1's other certificate warning
        already prints, plus BoundThumbprint for when the bound certificate
        cannot be found in the store to fingerprint.
    #>
    if (-not (Test-Path $certPath) -or -not $siteName) { return $null }
    $bound = Get-BoundCertThumbprint -SiteName $siteName
    if (-not $bound) { return $null }

    $pem = Get-Content -Raw $certPath
    $b64 = [regex]::Match($pem, '(?s)-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----').Groups[1].Value
    if (-not $b64) { return $null }
    $der = [Convert]::FromBase64String(($b64 -replace '\s', ''))
    # Thumbprints, not fingerprints, for the comparison itself: the bound
    # certificate is in Cert:\LocalMachine\My rather than a PEM file, and its
    # thumbprint is what identifies it there - the same SHA-1 identity
    # X509Certificate2 computes for any certificate, off the same DER bytes
    # Get-CertFingerprint hashes for display.
    $fileThumb = (New-Object Security.Cryptography.X509Certificates.X509Certificate2 (, $der)).Thumbprint
    if ($fileThumb -eq $bound) { return $null }

    $boundCert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $bound }
    return @{
        FileFingerprint  = Get-CertFingerprint $certPath
        BoundFingerprint = if ($boundCert) { Get-CertFingerprint -Der $boundCert.RawData } else { $null }
        BoundThumbprint  = $bound
    }
}

# -- Settings ------------------------------------------------------------
Step "Resolving settings"

. (Join-Path $PSScriptRoot "_deploy.ps1")
Initialize-DeploySettings $ConfigPath $PSBoundParameters $PSScriptRoot

$TargetDir  = Resolve-Setting "TargetDir"  $TargetDir  $null "installDir"
$BaseUrl    = Resolve-Setting "BaseUrl"    $BaseUrl    ""    "baseUrl"
$PythonExe  = Resolve-Setting "PythonExe"  $PythonExe  ""    "pythonExe"

# Nothing named one, so ask where this script is standing: the package installs
# it to <TargetDir>\tools\, and Resolve-InstallFromTools is what reads that
# back - with the two guards a repo checkout needs, which is why it is there
# rather than here. installed.json is this script's own record, so a
# never-updated install has none and server_config.json answers for that one;
# run_server.py is no marker at all, sitting at the repo root.
if (-not $TargetDir) {
    $TargetDir = Resolve-InstallFromTools $PSScriptRoot @($StateFile, "server_config.json")
    if ($TargetDir) { $TargetFrom = "this script's own install" }
}

# Checked before the package directory is built rather than after: dist\ hangs
# off this, and Join-Path refuses an empty parent with a message about argument
# binding instead of the one below.
if (-not $TargetDir) {
    Fail ("No TargetDir. Pass -TargetDir, or set installDir in deploy.json.`n" +
          "    Taken from this script's own location only where it sits in an" +
          " install's tools\ directory.")
}

# One place, and it is on the machine being updated: dist\ under the install
# directory. This script is installed to <TargetDir>\tools\ by the package it
# applies, so the updater and the releases it reads are two parts of one install.
# The four-place search that stood here - the working directory, deploy.json, the
# repo - existed for an updater carried to a machine by hand, and every one of
# those places was a guess about where the person carrying it had been standing.
#
# -PackageDir is still the one-off, and is then the only place looked: falling
# through to a directory the caller did not name would install a package they
# never pointed at.
#
# It is looked at twice either way: <dir>\<version>\ first, then <dir> itself.
# package.ps1 writes dist\<version>\ and that whole directory is the unit that
# gets carried to a machine, while a zip carried on its own lands beside it - so
# both shapes are looked for, in that order, and the line printed says which
# answered.
$PackageFrom = $null
if ($PSBoundParameters.ContainsKey("Package")) { $PackageFrom = "-Package" }

if ($PSBoundParameters.ContainsKey("PackageDir")) {
    # A file rather than a directory is the package itself, and is read as
    # -Package. Nothing is being guessed between the two readings: a leaf is
    # never a directory, so they cannot both hold. What the directory reading
    # does with a zip's own path is look in <zip>\<version>\ and <zip>\,
    # two directories that cannot exist - so the only other answer is a refusal
    # naming the file it was pointed at as somewhere it could not look, which is
    # what it gave. The version is then the manifest's, as it is on every run:
    # -Version is not consulted again, so a package whose name spells the
    # version differently still installs as itself rather than being refused
    # for a name it was never asked about.
    if (Test-Path -LiteralPath $PackageDir -PathType Leaf) {
        $Package     = $PackageDir
        $PackageFrom = "-PackageDir, which names a file"
    }
    $PackageRoot = @{ Dir = $PackageDir; From = "-PackageDir" }
} else {
    $PackageRoot = @{ Dir  = (Join-Path $TargetDir "dist")
                      From = "dist\ under the install directory" }
}

$PackageDirs = @()
if ($Version) {
    # No version to expand with under -Package: that parameter set names the zip
    # outright, and $Version belongs to the other one. Join-Path refuses an empty
    # child path rather than returning the parent, so this is a guard and not a
    # tidiness.
    $PackageDirs += @{ Dir  = (Join-Path $PackageRoot.Dir $Version)
                       From = "$($PackageRoot.From), $Version\" }
}
$PackageDirs += $PackageRoot

# Keys this script used to read and no longer does. Left unsaid, a deploy.json
# that names one would have it read by nothing and the run would say nothing
# about it - a machine that has been updating out of distDir would quietly start
# reading from somewhere else, which is the one thing the printed line exists to
# prevent. distDir is not dead everywhere: it is still package.ps1's ship root on
# a build machine, which is why this says what it says rather than calling the key
# a mistake.
$StaleKeys = @()
if ($DeployConfig) {
    foreach ($k in @("packageDir", "distDir")) {
        $v = "$($DeployConfig.$k)".Trim()
        if ($v) { $StaleKeys += "$k ($v)" }
    }
}
if ($StaleKeys) {
    Warn "deploy.json still sets $($StaleKeys -join " and ")."
    Warn "    Not read here any more: this script installs from dist\ under the install"
    Warn "    directory. Drop the release there, or pass -PackageDir for a one-off."
    Warn "    distDir is still package.ps1's ship root on a build machine; packageDir"
    Warn "    is read nowhere at all."
}

$CanPrompt = Test-CanPrompt $WhatIfPreference

Info "targetDir : $TargetDir$(if ($TargetFrom) { "  (from $TargetFrom)" })"
if ($Package) {
    Info "package   : $Package  (from $PackageFrom)"
} else {
    Info "package   : $($PackageRoot.Dir)  (from $($PackageRoot.From))"
}
Info "baseUrl   : $(if ($BaseUrl) { $BaseUrl } else { '(none - no health check)' })"

# -- Resolve the package ------------------------------------------------------------
Step "Resolving the package"

if ($Package) {
    $zipPath = $Package
    if (-not (Test-Path $zipPath)) {
        # The containing directory, not $PackageDirs: an explicit path was
        # given, so listing somewhere it was never pointed at is noise.
        Fail ("no such package: $zipPath`n    available: " +
              (Format-ZipListing (Split-Path -Parent $zipPath)))
    }
} else {
    # Looping, because a set of directories that holds no package for this
    # version is very often one answer away from one that does: the zip is
    # carried to the machine by hand and lands wherever the person carrying it
    # was standing. Failing instead means resolving every setting again from
    # the top for a question that could have been asked. An empty answer keeps
    # the refusal - there has to be a way to say no, and a run with nobody at
    # it has already said it, so there the old failure stands unchanged.
    $zipPath   = $null
    $searching = $PackageDirs
    while (-not $zipPath) {
        foreach ($c in $searching) {
            # package.ps1 writes AssetManager-<v>.zip. The -source suffix it
            # wrote before that is still resolved, because a machine can be
            # holding one - and so is the same bare name written by an exe
            # package from before 061. Both in one directory is genuinely
            # ambiguous - installing the wrong one replaces a source install
            # with exes, or an install with an older package of the same
            # version - so it refuses rather than guesses, and refuses
            # outright: that is not a package it failed to find, and neither
            # the next directory nor another answer is the reply to it.
            $bareZip   = Join-Path $c.Dir "AssetManager-$Version.zip"
            $suffixZip = Join-Path $c.Dir "AssetManager-$Version-source.zip"
            $found  = @($bareZip, $suffixZip | Where-Object { Test-Path $_ })
            if ($found.Count -gt 1) {
                Fail ("two packages exist for $Version in $($c.Dir)`:`n" +
                      "    " + ($found -join "`n    ") +
                      "`n`n    pass -Package with the one you mean")
            }
            if ($found.Count -eq 1) {
                $zipPath = $found[0]
                Info "found in $($c.Dir)  (from $($c.From))"
                break
            }
        }
        if ($zipPath) { break }

        # A directory that does not exist is not refused separately: it is
        # reported as "no such directory" in the same line and the same place
        # as one that exists and is simply missing this version.
        Warn "no AssetManager-$Version.zip in any of:"
        foreach ($c in $searching) {
            Warn "    $($c.Dir)  ($($c.From)) - $(Format-ZipListing $c.Dir)"
        }
        if (-not $CanPrompt) { Fail "no such package: AssetManager-$Version.zip" }
        $answer = (Read-Host "  Directory holding the package (Enter to give up)").Trim()
        if (-not $answer) { Fail "no such package: AssetManager-$Version.zip" }
        # The answer replaces the search rather than extending it: the places
        # already looked in have just been listed as not holding it.
        $searching = @(@{ Dir = $answer; From = "answered at the prompt" })
    }
}
$zipPath = (Resolve-Path $zipPath).Path
Info $zipPath

# -- Extract and verify ------------------------------------------------------------
Step "Verifying the package"

$work = Join-Path ([IO.Path]::GetTempPath()) ("am-upd-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null

try {
    Expand-Archive -Path $zipPath -DestinationPath $work
    $manifestPath = Join-Path $work "manifest.json"
    if (-not (Test-Path $manifestPath)) { Fail "package has no manifest.json" }
    $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json

    $bad = @()
    foreach ($prop in $manifest.files.PSObject.Properties) {
        $rel  = $prop.Name
        $want = $prop.Value
        $p    = Join-Path $work ($rel -replace '/', '\')
        if (-not (Test-Path $p)) { $bad += "$rel is listed in the manifest but missing"; continue }
        $got = (Get-FileHash -Path $p -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $want.ToLower()) { $bad += "$rel hash mismatch" }
    }
    if ($bad) { Fail ("package is corrupt:`n    " + ($bad -join "`n    ")) }

    $pkgVersion = $manifest.version
    $schema     = [int]$manifest.schema_version
    $pkgMode    = if ($manifest.mode) { $manifest.mode } else { "exe" }
    Info "mode: $pkgMode"

    # Installing an exe package over a source install, or the reverse, leaves
    # both sets of files in the directory. Resolve-ServerRunner then prefers the
    # exe, IIS keeps pointing wherever web.config says, and which code is
    # actually serving stops being obvious. Named here rather than blocked: a
    # deliberate migration between modes is a real thing to want.
    $hasExe = Test-Path (Join-Path $TargetDir "AssetServer.exe")
    $hasSrc = Test-Path (Join-Path $TargetDir "run_server.py")
    if ($pkgMode -eq "source" -and $hasExe) {
        Warn "this is a source package and $TargetDir still holds AssetServer.exe."
        Warn "Re-run install-iis.ps1 afterwards so web.config points at python,"
        Warn "and delete the exes once the source install is verified."
    }
    if ($pkgMode -eq "exe" -and $hasSrc -and -not $hasExe) {
        Warn "this is an exe package and $TargetDir is a source install."
        Warn "Re-run install-iis.ps1 afterwards so web.config points at the exe."
    }
    Info "version $pkgVersion, schema v$schema, commit $($manifest.git_commit.Substring(0,12))"
    Info "$(@($manifest.files.PSObject.Properties).Count) files, hashes verified"

    if ($manifest.git_dirty -and -not $AllowDirty) {
        Fail ("package $(Split-Path -Leaf $zipPath) was built from a dirty tree and must not`n" +
              "be deployed (-AllowDirty overrides)")
    }

    # -- Work out the direction ------------------------------------------------------------
    Step "Planning"

    if (-not (Test-Path $TargetDir)) {
        if ($PSCmdlet.ShouldProcess($TargetDir, "Create install directory")) {
            New-Item -ItemType Directory -Path $TargetDir | Out-Null
        }
    }
    $TargetDir = (Resolve-Path $TargetDir).Path

    $statePath = Join-Path $TargetDir $StateFile
    $installed = $null
    if (Test-Path $statePath) {
        $installed = (Get-Content -Raw $statePath | ConvertFrom-Json).version
    }
    $direction =
        if (-not $installed) { "install" }
        else {
            switch (Compare-SemVer $pkgVersion $installed) {
                1  { "upgrade" }
                -1 { "downgrade" }
                0  { "reinstall" }
            }
        }
    Info "$direction : $(if ($installed) { $installed } else { 'none' }) -> $pkgVersion"

    # Resolve-DbPath, not Join-Path: this path is what gets backed up and
    # migrated, and an install that moved its database with db_path would
    # otherwise have an empty one created, migrated and declared fine while the
    # real database sat untouched at the wrong schema version.
    $db          = Resolve-DbPath $TargetDir
    $rollback    = Join-Path $TargetDir ("rollback\" + $(if ($installed) { $installed } else { "unknown" }))
    $stagedMig   = Join-Path $TargetDir "migrations"
    # Resolved before anything is stopped or written, and asked about there
    # rather than guessed: an install whose iis.json is missing or stale used
    # to be sent to sc.exe, which stops nothing on an IIS host.
    $appPool     = Resolve-HostAppPool $TargetDir $CanPrompt
    # iis.json again, directly: Resolve-HostAppPool answers with the app pool
    # alone, and reconciling a certificate mismatch needs the site name too,
    # to read and rebind an SSL binding, which is a site's rather than a
    # pool's. Re-read rather than widening that function's return contract,
    # so a site named only at the interactive prompt there - never written to
    # iis.json - leaves $iisSite unresolved and this reconcile a no-op, which
    # is the same "no IIS host to reconcile against" case as no iis.json at
    # all.
    $iisSite = $null
    if ($appPool) {
        try {
            $iis = Read-JsonFile (Join-Path $TargetDir "iis.json")
            if ($iis -and "$($iis.site)".Trim()) { $iisSite = "$($iis.site)".Trim() }
        } catch { }
    }

    if ($WhatIfPreference) {
        Info "would stop $(if ($appPool) { "app pool $appPool" } else { "service $ServiceName" })"
        Info "would copy $db, and any -wal and -shm beside it, into $rollback"
        Info "would migrate $db to schema v$schema"
        Info "would move lib\ into $rollback and write the package's in its place"
        Info "would write $(@($manifest.files.PSObject.Properties).Count) files to $TargetDir"
        $mismatch = Get-CertMismatch (Join-Path $TargetDir "ssl_cert.pem") $iisSite
        if ($mismatch) {
            Info "ssl_cert.pem does not match the certificate bound to IIS site ${iisSite}:"
            Info "  ssl_cert.pem : $($mismatch.FileFingerprint)"
            Info "  IIS binding  : $(if ($mismatch.BoundFingerprint) { $mismatch.BoundFingerprint } else { $mismatch.BoundThumbprint })"
            Info "would reconcile: import ssl_cert.pem/ssl_key.pem into LocalMachine\My and rebind IIS site $iisSite to it"
        }
        return
    }

    # -- Stop the host ------------------------------------------------------------
    Step "Stopping the host"

    if ($appPool) {
        Import-Module WebAdministration
        Stop-WebAppPool -Name $appPool -ErrorAction SilentlyContinue
        Info "stopping IIS app pool $appPool"
    } else {
        & sc.exe stop $ServiceName | Out-Null
        Info "stopping service $ServiceName (exit $LASTEXITCODE)"
    }

    # Waited for, not slept through. Both Stop- calls return before the worker
    # has gone: HttpPlatformHandler gives the process its shutdownTimeLimit,
    # 10s by default, and sc.exe stop only asks. A fixed two-second sleep was
    # enough for the listener to release the port, which is all it was ever
    # there for - it is not enough to know that nothing is still writing to the
    # database, which is what the copy below now depends on.
    $stopped = $false
    foreach ($i in 1..20) {
        if ($appPool) {
            $st = (Get-WebAppPoolState -Name $appPool -ErrorAction SilentlyContinue).Value
            if (-not $st -or $st -eq "Stopped") { $stopped = $true; break }
        } else {
            $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
            if (-not $svc -or $svc.Status -eq "Stopped") { $stopped = $true; break }
        }
        Start-Sleep -Milliseconds 500
    }
    if ($stopped) {
        Info "host is down"
    } else {
        # Not fatal: an app pool wedged in Stopping still has to be updated,
        # and refusing here would leave the operator with a stopped server and
        # no way forward. Said out loud, because it is the one condition under
        # which the copy below can catch a half-written page.
        Warn "the host did not report Stopped within 10s - it may still be writing."
        Warn "Check the database copy in the rollback directory before relying on it."
    }

    # -- Back up the database ------------------------------------------------------------
    Step "Backing up the database"

    # After the host is stopped rather than before it, deliberately. A file
    # copy of a live SQLite database can catch a half-written page, and in WAL
    # mode the database and its -wal are two files that have to agree with each
    # other - copied one after the other under a server that is still writing,
    # they do not. Stopping first is the only way to take the three cleanly, so
    # this is the first thing after the stop and still before anything on disk
    # is written: the state saved here is the install as it was last known good.
    #
    # -wal and -shm are usually gone by now, because a clean shutdown
    # checkpoints and removes them. They are here for the shutdown that was not
    # clean, where the -wal holds committed transactions the database does not.
    if (Test-Path $db) {
        $dbCopy = Join-Path $rollback (Split-Path -Leaf $db)
        if (Test-Path $dbCopy) {
            # A second run of the same update resolves the same rollback
            # directory, because a failed health check leaves the installed
            # version where it was - installed.json is restored with every
            # other file this run replaced, which is what makes that true
            # (#111). Overwriting would replace the copy taken before the
            # first migration with one taken after it - destroying the very
            # file the failure message tells somebody to restore.
            Info "a copy is already in $rollback from an earlier run - kept, not overwritten"
        } else {
            try {
                foreach ($suffix in @("", "-wal", "-shm")) {
                    $src = "$db$suffix"
                    if (Test-Path $src) {
                        Copy-Into $src (Join-Path $rollback (Split-Path -Leaf $src))
                        Info "saved $(Split-Path -Leaf $src)"
                    }
                }
            } catch {
                # Said the way every other refusal in this script says it. A
                # disk-full or a locked -wal here would otherwise throw a raw
                # PowerShell error and leave the operator with a stopped server
                # and no statement of what had happened to it.
                Fail ("could not copy the database aside: $($_.Exception.Message)`n" +
                      "    nothing was replaced, host still stopped - start it again with`n" +
                      "    $(if ($appPool) { "Start-WebAppPool -Name $appPool" } else { "sc.exe start $ServiceName" })")
            }
            Info "database saved to $rollback (a rollback never restores it - by hand only)"
        }
    } else {
        Info "no database yet - nothing to back up"
    }

    # -- Migrations ------------------------------------------------------------
    Step "Migrating the database to schema v$schema"

    # Migration files are MERGED, never replaced. Downgrading needs the down()
    # that shipped with the newer build, which is already staged here from the
    # previous install and is absent from the older package. Files are numbered
    # and immutable, so keeping both sets is safe.
    if (-not (Test-Path $stagedMig)) { New-Item -ItemType Directory -Path $stagedMig | Out-Null }
    $pkgMig = Join-Path $work "migrations"
    if (Test-Path $pkgMig) {
        foreach ($f in Get-ChildItem $pkgMig -Filter *.py) {
            Copy-Item $f.FullName (Join-Path $stagedMig $f.Name) -Force
        }
    }
    Info "$((Get-ChildItem $stagedMig -Filter *.py).Count) migration file(s) staged"

    if (Test-Path $db) {
        # Resolved against the install directory as it is now, before the swap:
        # on a downgrade the currently-installed build is the one that knows the
        # down() being applied. An exe install and a source install differ only
        # in which process gets started.
        $runner = Resolve-ServerRunner $TargetDir $PythonExe
        if (-not $runner) {
            Fail ("cannot migrate: neither AssetServer.exe nor run_server.py is in`n" +
                  "    $TargetDir, and one of them runs the migrations")
        }
        & $runner.File @($runner.Prefix +
            @("migrate", "--db", $db, "--dir", $stagedMig, "--target", $schema))
        if ($LASTEXITCODE -ne 0) {
            Fail ("migration failed - nothing was replaced, host still stopped.`n" +
                  "    The database as it was before this run is in $rollback, and the`n" +
                  "    migration writes its own .bak-v* beside $db. Restore by hand,`n" +
                  "    with the host stopped and the -wal and -shm moved with it.")
        }
    } else {
        Info "no database yet - init_db() creates it on first start"
    }

    # -- Swap the exes ------------------------------------------------------------
    Step "Installing files"

    # $rollback was resolved in Planning and the database is already in it.
    if (-not (Test-Path $rollback)) { New-Item -ItemType Directory -Path $rollback -Force | Out-Null }

    # lib\ goes aside as ONE thing, and what the package writes into is then an
    # empty directory rather than the previous pin set. Writing file by file
    # removes nothing, so a pin whose file set changed - a renamed or split
    # module, a dropped submodule, the <pkg>-<version>.dist-info every bump
    # renames - left the old files on sys.path beside the new ones. Rule 13 ties
    # this directory to one Python minor and PYVER catches that; nothing catches
    # a half-merged pin set.
    #
    # It is sharpest on the way back. The restore below puts back what was
    # overwritten, and a file only the incoming lib\ carried was never saved, so
    # the rollback that exists to reach a known-good state produced a tree
    # neither release ever shipped - and a downgrade, which is the moment
    # somebody is backing out of a build that does not work, did the same thing
    # without failing at all.
    #
    # installer.py replaces this directory wholesale and client_update.py moves
    # it wholesale, both for exactly this reason; this is the third applier
    # agreeing with them, and moving rather than copying for the reason
    # client_update.py gives - several hundred copies of a directory that has to
    # go back as one thing anyway.
    $pkgHasLib = @($manifest.files.PSObject.Properties |
                   Where-Object { $_.Name -like "lib/*" }).Count -gt 0
    $libDir    = Join-Path $TargetDir "lib"
    $libSave   = Join-Path $rollback "lib"
    if ($pkgHasLib -and (Test-Path $libDir)) {
        if (Test-Path $libSave) {
            # Kept, not overwritten, for the reason the database copy beside it
            # is kept: a failed health check leaves the installed version where
            # it was, so a second run of the same update resolves this same
            # rollback directory - and what is already in it was taken before
            # anything had been replaced.
            Info "a lib\ is already in $rollback from an earlier run - kept, not overwritten"
            Remove-Item $libDir -Recurse -Force
        } else {
            Move-Item $libDir $libSave
            Info "saved lib\ to $rollback"
        }
    }

    # Everything else the package will overwrite, not just the exes. A package
    # can also carry ssl_cert.pem and config.json, and those were being replaced
    # with no saved copy - so an auto-rollback restored the old exes next to a
    # new certificate, which is the one combination that strands every client.
    # lib\ is out of this list because it has already gone aside whole, and a
    # per-file restore over a wholesale one would put half of each back.
    $incoming = @($manifest.files.PSObject.Properties |
                  Where-Object { $_.Name -notlike "migrations/*" -and
                                 $_.Name -notlike "lib/*" } |
                  ForEach-Object { $_.Name })
    # installed.json is this script's own record rather than a packaged file, so
    # the manifest cannot name it - and it was the one file this run overwrote
    # and never put back. A rollback then left the old build running beside a
    # state file naming the version that had just been rolled back, which is the
    # premise the database guard above rests on: the next run reads that version,
    # calls the upgrade a reinstall, and resolves rollback\<new-version>, which
    # is empty - so the guard does not fire and the database already migrated
    # forward by the failed run is copied in as that run's "before" copy, which
    # is the very file the failure message sends somebody to restore (#111).
    # It goes in the list rather than beside it: one list is what keeps the save
    # below and the restore at the end from disagreeing about what was replaced.
    $incoming += $StateFile
    foreach ($rel in $incoming) {
        $cur = Join-Path $TargetDir $rel
        if (Test-Path $cur) { Copy-Into $cur (Join-Path $rollback $rel) }
    }
    Info "previous files saved to $rollback"

    # Worth saying out loud rather than leaving to be discovered: a client
    # refreshes GET /cert over a connection its current ssl_cert.pem has already
    # verified, so replacing the served certificate with an unrelated one is
    # exactly what stops that refresh working - and the clients fail closed.
    #
    # Both fingerprints are named because that is the question actually being
    # asked at that moment: is this the certificate the server is meant to be
    # serving, or a stale copy that travelled in the package? One hash on its
    # own can be compared with nothing.
    if ($incoming -contains "ssl_cert.pem") {
        $curCert = Join-Path $TargetDir "ssl_cert.pem"
        $newCert = Join-Path $work "ssl_cert.pem"
        if ((Test-Path $curCert) -and
            (Get-Content -Raw $curCert) -ne (Get-Content -Raw $newCert)) {
            Warn "this package replaces ssl_cert.pem with a DIFFERENT certificate."
            Warn "  installed: $(Get-CertFingerprint $curCert)"
            Warn "  package  : $(Get-CertFingerprint $newCert)"
            Warn "Clients holding the installed one fail closed against the new"
            Warn "certificate - they verify against the copy they already have, so the"
            Warn "hourly GET /cert refresh cannot get through either. Each one has to be"
            Warn "reinstalled, or have its ssl_cert.pem deleted so the person at that"
            Warn "machine is asked to confirm the new fingerprint on first contact"
            Warn "(ADR-0010). The outgoing copy is in $rollback."
        }
    }

    foreach ($prop in $manifest.files.PSObject.Properties) {
        $rel = $prop.Name
        if ($rel -like "migrations/*") { continue }      # already staged above
        Copy-Into (Join-Path $work ($rel -replace '/', '\')) (Join-Path $TargetDir $rel)
    }
    Info "wrote $(@($manifest.files.PSObject.Properties | Where-Object { $_.Name -notlike 'migrations/*' }).Count) files to $TargetDir"

    $state = [ordered]@{
        version        = $pkgVersion
        schema_version = $schema
        git_commit     = $manifest.git_commit
        installed_at   = (Get-Date).ToString("s")
    }
    Write-JsonFile $statePath $state

    # -- Start ------------------------------------------------------------
    Step "Starting the host"

    $hostStarted = $true
    if ($appPool) {
        try {
            Start-WebAppPool -Name $appPool
            Info "started app pool $appPool"
        } catch {
            $hostStarted = $false
            Warn "app pool $appPool did not start: $($_.Exception.Message)"
        }
    } else {
        & sc.exe start $ServiceName | Out-Null
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1056) {
            $hostStarted = $false
            Warn "service $ServiceName did not start (exit $LASTEXITCODE)"
        } else {
            Info "started service $ServiceName (exit $LASTEXITCODE)"
        }
    }

    # -- Health check ------------------------------------------------------------
    if ($SkipHealth -or -not $BaseUrl) {
        Warn "no -BaseUrl given - skipping the health check and auto-rollback"
        if ($hostStarted) {
            Write-Host "`n[OK] $direction to $pkgVersion complete (unverified)" -ForegroundColor Yellow
        } else {
            Write-Host "`n$direction to $pkgVersion complete, but the host did not start (unverified)" -ForegroundColor Yellow
        }
        return
    }

    Step "Health check"

    $url = $BaseUrl.TrimEnd('/') + "/version"
    $ok  = $false
    $last = $null
    # Pinned on <InstallDir>\ssl_cert.pem, through _deploy.ps1's one
    # implementation of that: an https $BaseUrl against a server carrying the
    # certificate install-iis.ps1 -SelfSigned minted could not be verified at
    # all from 5.1, so every attempt threw, $ok stayed false, and this script
    # rolled a good update back over a database it had already migrated
    # forward - the one state its own failure message sends somebody to sort
    # out by hand. That file is the one the clients pin and GET /cert serves,
    # so it is also the right thing to hold this server to.
    foreach ($i in 1..10) {
        Start-Sleep -Seconds 2
        $last = Invoke-PinnedRequest -Url $url -TimeoutSec 5 `
                                     -PinPath (Join-Path $TargetDir "ssl_cert.pem")
        if ($last.StatusCode -ne 200) {
            Info "attempt $i/10 : $($last.Error)"
            continue
        }
        $latest = $null
        try { $latest = (ConvertFrom-Json $last.Content).latest } catch { }
        if ($latest -eq $pkgVersion) { $ok = $true; break }
        Info "/version reports $latest, expected $pkgVersion"
    }

    if (-not $ok -and $iisSite) {
        # ssl_cert.pem is the source of truth - it is what GET /cert serves
        # and what every client has already pinned - so a bound certificate
        # that disagrees with it is corrected to match the file, never the
        # other way: rebinding to whatever IIS happened to have would strand
        # every client that already pinned the file. Where there is no IIS
        # host at all - the service, or a standalone install - $iisSite is
        # $null and this block never runs; the mismatch warning above stands
        # exactly as it did before this reconcile existed.
        #
        # Reconciled here, after the ten-attempt health check has already
        # failed once against the mismatch (Invoke-PinnedRequest can never
        # succeed against a certificate other than the one it is pinned on),
        # and before the run is called good - so a rebind that itself fails
        # simply leaves $ok false and falls straight into the same rollback
        # below as any other failed health check, with no rollback logic of
        # its own to keep in step with that one.
        $certPath = Join-Path $TargetDir "ssl_cert.pem"
        $keyPath  = Join-Path $TargetDir "ssl_key.pem"
        try {
            $mismatch = Get-CertMismatch $certPath $iisSite
            if ($mismatch) {
                Warn "IIS site $iisSite is bound to a certificate other than ssl_cert.pem:"
                Warn "  ssl_cert.pem : $($mismatch.FileFingerprint)"
                Warn "  IIS binding  : $(if ($mismatch.BoundFingerprint) { $mismatch.BoundFingerprint } else { $mismatch.BoundThumbprint })"
                Info "reconciling: importing ssl_cert.pem/ssl_key.pem and rebinding IIS site $iisSite"
                $thumb = Import-CertPair -CertPath $certPath -KeyPath $keyPath
                Set-SiteCertificate -SiteName $iisSite -Thumbprint $thumb
                Info "rebound IIS site $iisSite to $thumb"

                foreach ($i in 1..5) {
                    Start-Sleep -Seconds 2
                    $last = Invoke-PinnedRequest -Url $url -TimeoutSec 5 -PinPath $certPath
                    if ($last.StatusCode -ne 200) {
                        Info "attempt $i/5 : $($last.Error)"
                        continue
                    }
                    $latest = $null
                    try { $latest = (ConvertFrom-Json $last.Content).latest } catch { }
                    if ($latest -eq $pkgVersion) { $ok = $true; break }
                    Info "/version reports $latest, expected $pkgVersion"
                }
            }
        } catch {
            Warn "reconcile failed: $($_.Exception.Message)"
        }
    }

    if ($ok) {
        Write-Host "`n[OK] $direction to $pkgVersion verified - /version reports $pkgVersion" -ForegroundColor Green
        return
    }

    Warn "HEALTH CHECK FAILED - restoring the previous files from $rollback"
    if ($last -and $last.Pinned -and $last.Presented -and $last.Presented -ne $last.Pinned) {
        # Not a bad build: the server is serving a certificate that is not the
        # one in the install directory, which is the mismatch warned about
        # above when a package carries its own ssl_cert.pem. Naming both is
        # what the warning up there exists for, and the rollback below puts
        # the installed file back, so the two agree again afterwards.
        Warn "  the server presented a certificate other than <InstallDir>\ssl_cert.pem:"
        Warn "    installed: $($last.Pinned)"
        Warn "    served   : $($last.Presented)"
    }
    if ($appPool) { Stop-WebAppPool -Name $appPool -ErrorAction SilentlyContinue }
    else          { & sc.exe stop $ServiceName | Out-Null }
    Start-Sleep -Seconds 2
    # $incoming: whatever this run overwrote is what has to go back - the
    # package's own files and installed.json, which the manifest cannot name
    # and which says which build is on the machine (#111). The database is
    # deliberately not in that list, and is never put back here:
    # the new build has been serving for as long as the health check took, and
    # any transaction recorded in that time is only in the live file.
    # Restoring the old code but leaving a new ssl_cert.pem in place is a
    # rollback that still strands every client.
    foreach ($rel in $incoming) {
        $src = Join-Path $rollback $rel
        if (Test-Path $src) { Copy-Into $src (Join-Path $TargetDir $rel) }
    }
    # And lib\ as one thing, the way it went aside. Copied rather than moved
    # back, so what is in the rollback directory stays the record of the install
    # as it was - the same reason nothing else here is moved out of it.
    if ($pkgHasLib -and (Test-Path $libSave)) {
        if (Test-Path $libDir) { Remove-Item $libDir -Recurse -Force }
        Copy-Item $libSave $libDir -Recurse -Force
        Info "restored lib\ from $rollback"
    }
    if ($appPool) { Start-WebAppPool -Name $appPool }
    else          { & sc.exe start $ServiceName | Out-Null }

    Fail ("rolled back to $installed. The database was left alone on purpose - anything`n" +
          "recorded since the update is only in it. It is still at schema v$schema; if that`n" +
          "build cannot read it, restore one of these by hand, having looked first:`n" +
          "    the copy taken before the migration : $rollback`n" +
          "    the migration's own backup          : the .bak-v* file next to $db")
}
finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
