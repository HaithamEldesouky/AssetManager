# Settings resolution shared by install-iis.ps1, update.ps1, package.ps1,
# migrate.ps1 and bundle-client.ps1, plus the JSON file helpers below, which
# dev-run.ps1 dot-sources this file for on its own, and two helpers the
# release scripts share: Get-VendoredPyVer (package.ps1 asks it of lib-server,
# bundle-client.ps1 of lib-client), Get-CertFingerprint (package.ps1 prints one,
# update.ps1 and install-iis.ps1 name both sides of a replacement with it) and
# Invoke-PinnedRequest (update.ps1 health-checks with it, install-iis.ps1
# probes with it).
#
# A cutover or an update is otherwise a long command line retyped from a runbook,
# once per machine, with the install directory and the port in it. deploy.json
# holds those instead, and anything passed on the command line still wins over
# the file - so an override needs no edit to the file, and the file is what makes
# a repeat run reproducible.
#
# Dot-sourced rather than a module: these scripts get run from a copied tools\
# directory on a server where nothing is installed and $env:PSModulePath is
# whatever it was, and dot-sourcing needs neither. The functions therefore run in
# the caller's scope, and the $script:Deploy* variables below belong to the
# calling script.
#
# The caller must define Info and Fail before dot-sourcing this file, and passes
# its own $PSScriptRoot to Initialize-DeploySettings rather than this file
# reading $PSScriptRoot from inside a function, where it is the defining file's
# directory and not obviously so to anyone reading the call.

function Read-JsonFile([string] $path) {
    <#
        The parsed contents of a JSON file, or $null when the file is not
        there.

        There are three states and a caller that cares answers each of them
        differently: absent is $null, readable is the object, and
        present-but-not-JSON throws - which is why this does not catch.
        Get-DeployConfig fails on that, Resolve-DbPath falls back to the default
        database, install-iis.ps1 leaves the file it cannot read alone, and
        update.ps1 carries on with the Windows service. A helper that caught it
        would be choosing one of those four answers for all four. dev-run.ps1 is
        the fifth call site and answers none of them: it stages a tree it owns,
        under $ErrorActionPreference = "Stop", where a corrupt config should stop
        the run.

        What it centralises is the read. Get-Content -Raw strips a BOM on both
        editions, so a file written by Set-Content -Encoding UTF8 under Windows
        PowerShell 5.1 still reads back cleanly here - it is the Python end of
        those same files that cannot, which is what Write-JsonFile below is for.

        It is for JSON *objects*. A top-level array comes back unrolled by the
        pipeline - a one-element array as the bare element, an empty one as
        $null, which is this function's own word for "no file" - so an array
        file has to be read with the @(... | ForEach-Object { $_ }) that trap
        seven prescribes. dev-run.ps1's pid file is the one of those here, and
        it deliberately does not come through here.
    #>
    if (-not (Test-Path $path)) { return $null }
    return (Get-Content -Raw $path | ConvertFrom-Json)
}


function Write-JsonFile([string] $path, $value, [int] $depth = 5) {
    <#
        Write $value to $path as JSON, UTF-8 with no BOM.

        Not "Set-Content -Encoding UTF8": under Windows PowerShell 5.1 that
        switch means UTF-8 *with* a BOM, and every Python app here reads its
        config with a plain open()/json.load, which decodes that BOM as cp1252
        and dies on "Expecting value: line 1 column 1 (char 0)". utf8NoBOM
        exists only in PS 6+, so the bytes go through .NET with a no-BOM encoder
        instead. That is trap six in CLAUDE.md, and it is here rather than in
        each writer because there were two copies of it - one in install-iis.ps1
        and one in dev-run.ps1 - which is a security-shaped spelling written
        down twice, the thing rule 10 exists to prevent. 054 had just folded
        install-iis.ps1's own two writes onto the first of those, declining to
        share it on the grounds that two writers inside one file is not yet a
        pattern; that is about call sites within a file, and this is about the
        function itself existing twice across two.

        The path is resolved first because .NET has its own current directory: a
        relative -InstallDir or -DevDir would otherwise land the file somewhere
        else entirely.
    #>
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($path)
    [IO.File]::WriteAllText($full, ($value | ConvertTo-Json -Depth $depth),
                            (New-Object Text.UTF8Encoding $false))
}


function Get-DeployConfig([string] $explicit, [string] $searchDir) {
    $candidates = @()
    if ($explicit) {
        $candidates += $explicit
    } else {
        # Next to the scripts first, then the repo root: a checkout can carry one
        # file for the whole repo, and a copied tools\ directory its own.
        $candidates += (Join-Path $searchDir "deploy.json")
        $candidates += (Join-Path (Split-Path -Parent $searchDir) "deploy.json")
    }
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            try {
                $json = Read-JsonFile $c
            } catch {
                Fail "not valid JSON: $c`n    $($_.Exception.Message)"
            }
            Info "config    : $c"
            return $json
        }
    }
    if ($explicit) { Fail "config file not found: $explicit" }
    Info "config    : none found; using parameters only"
    return $null
}

function Initialize-DeploySettings([string] $configPath, $boundParameters, [string] $searchDir) {
    $script:DeployGiven  = $boundParameters
    $script:DeployConfig = Get-DeployConfig $configPath $searchDir
}

# Returns the value a setting should have: the parameter if one was passed, else
# the config file, else the default.
#
# Tested against $PSBoundParameters rather than emptiness, so a parameter passed
# explicitly is honoured over the file even when it equals the default.
#
# $key is for the few settings whose parameter name differs from the config key:
# update.ps1 calls its install directory -TargetDir, but it is the same directory
# install-iis.ps1 calls -InstallDir, and one deploy.json should describe it once.
function Resolve-Setting([string] $name, $current, $fallback, [string] $key) {
    if (-not $key) { $key = $name }
    if ($script:DeployGiven -and $script:DeployGiven.ContainsKey($name)) { return $current }
    $cfg = $script:DeployConfig
    if ($cfg -and $null -ne $cfg.$key -and "$($cfg.$key)" -ne "") { return $cfg.$key }
    return $fallback
}

function Resolve-InstallFromTools([string] $toolsDir, [string[]] $markers) {
    <#
        The install directory a tools\ directory is part of, or $null.

        update.ps1 ships inside the server package and is installed to
        <InstallDir>\tools\, and dist\ under that same install is the one
        place it reads a package from - so the updater and the install it
        applies to are two parts of one thing, and the parent of this script
        says which install that is. No deploy.json ships in any package, so
        without this a server that never had one written by hand fails at the
        first step of the update every runbook spells -Version and nothing
        else.

        Guarded twice, because a repo checkout has a tools\ of its own. One
        of $markers has to sit beside it - the caller names them, so the
        state file's own name stays written down once, in the script that
        writes it - and there must be no .git there, since a checkout that
        has ever run the server carries a server_config.json in its root and
        would otherwise answer the first test.

        Here rather than inline in update.ps1, which is its only caller, for
        Test-FirstTimeCertSetup's reason: that script stops an app pool and
        overwrites an install, so no gate can run it, while this file is the
        one every script here dot-sources and so the one a harness can
        dot-source too. deploy-checks.ps1 drives every state over it.
    #>
    if (-not $toolsDir) { return $null }
    $beside = Split-Path -Parent $toolsDir
    if (-not $beside) { return $null }
    if (Test-Path (Join-Path $beside ".git")) { return $null }
    foreach ($m in $markers) {
        if (Test-Path (Join-Path $beside $m)) { return $beside }
    }
    return $null
}

function Resolve-ServerRunner([string] $dir, [string] $pythonExe) {
    <#
        How to invoke server.py's own migrate/serve verbs in this install
        directory: AssetServer.exe if it is there, otherwise python plus
        run_server.py. Returns $null when neither is present.

        Shared because update.ps1 and migrate.ps1 both need exactly this and a
        wrong answer means a migration that silently does not run. The engine
        itself stays in server.py in both modes - PowerShell has no SQLite
        provider, so the decision is only which process to start.

        The interpreter is resolved through Get-Command before it is handed
        back, so File always carries a full path. That is vendor.ps1's rule
        one level out: $ErrorActionPreference is Stop in both callers, so a
        bare "python" that is not on PATH raises PowerShell's own
        CommandNotFoundException at the & rather than the refusal written
        under it - and in update.ps1 that & is reached after the app pool has
        been stopped and the database copied aside, so what it costs is a
        server that is down with no rollback and nothing naming pythonExe.
        The name is decided here, so this is where it is resolved, and one
        answer serves both callers.

        Returns @{ File = <what to execute>; Prefix = <args before the verb>;
                   Kind = "exe" | "source" }. Call it as:
            & $r.File @($r.Prefix + @("migrate", "--db", $db))
    #>
    $exe = Join-Path $dir "AssetServer.exe"
    if (Test-Path $exe) {
        return @{ File = $exe; Prefix = @(); Kind = "exe" }
    }
    $src = Join-Path $dir "run_server.py"
    if (Test-Path $src) {
        if (-not $pythonExe) { $pythonExe = "python" }
        $py = @(Get-Command $pythonExe -CommandType Application -ErrorAction SilentlyContinue)[0]
        if (-not $py) {
            Fail ("no Python interpreter for a source install: '$pythonExe' is" +
                  " not on PATH`n    and is not a file. Set pythonExe in" +
                  " deploy.json to the full path of`n    python.exe, or pass" +
                  " -PythonExe - it is what runs the migrations.")
        }
        return @{ File = $py.Source; Prefix = @($src); Kind = "source" }
    }
    return $null
}


function Resolve-DbPath([string] $dir) {
    <#
        Where this install's database actually is: db_path from the install's
        own server_config.json when it names one, otherwise assets.db beside
        the server.

        Shared for the same reason as Resolve-ServerRunner and for a sharper
        one. Every caller here backs the database up before touching it, and a
        backup written where the database no longer is, is worse than no
        backup: it succeeds, it is roughly the right size, and it is the wrong
        file. The same goes for a migration - pointed at the default path on an
        install that moved, it creates an empty database, migrates that, and
        reports success.

        A missing or unreadable server_config.json means the default. The
        server treats it the same way, and refusing here would block a
        migration on a config problem the migration does not care about. The
        server writes that file with a plain no-BOM UTF-8 encoder, so
        Get-Content -Raw reads it back cleanly on both editions.
    #>
    $cfgPath = Join-Path $dir "server_config.json"
    try {
        $cfg = Read-JsonFile $cfgPath
        if ($cfg) {
            $p = "$($cfg.db_path)".Trim()
            if ($p) { return $p }
        }
    } catch {
        Write-Host ("  ! could not read $cfgPath ($($_.Exception.Message))" +
                    " - assuming the default database")
    }
    return (Join-Path $dir "assets.db")
}


function Test-CanPrompt([bool] $whatIf) {
    <#
        Whether there is a human at this console to answer a question.

        UserInteractive alone is not enough: a scheduled task running as a
        logged-on user reports true with no console attached, and a Read-Host
        there waits for input that can never arrive until something kills the
        task. Under -WhatIf nothing is asked either - a rehearsal is the one
        safe way to check a run before it is pointed at a live server, so it
        must not be the run that blocks on a prompt. Where this returns false
        the caller's existing refusal stands, naming what was missing.

        $whatIf is a parameter rather than $WhatIfPreference read from in here.
        The preference is set per-invocation on the calling script and would
        reach this function by dynamic scoping - right today, and the kind of
        dependency a shared file should not have where a parameter costs one
        word at the call site. It is [bool], not [switch], for the reason
        Resolve-Switch gives.
    #>
    return [Environment]::UserInteractive -and
           -not [Console]::IsInputRedirected -and
           -not $whatIf
}


# Switches need their own resolver: an absent [switch] is not $null, it is
# false, so Resolve-Setting cannot tell "left off" from "passed -Foo:$false".
#
# $current is [bool], not [switch], on purpose. A switch parameter on a function
# is bound by name only - it is skipped during positional binding - so with
# [switch] here the caller's `Resolve-Switch "SelfSigned" $SelfSigned` quietly
# bound $SelfSigned to $key, looked up a config key named "False", found nothing
# and returned false for a config that said true.
function Resolve-Switch([string] $name, [bool] $current, [string] $key) {
    if (-not $key) { $key = $name }
    if ($script:DeployGiven -and $script:DeployGiven.ContainsKey($name)) { return [bool] $current }
    $cfg = $script:DeployConfig
    if ($cfg -and $null -ne $cfg.$key) { return [bool] $cfg.$key }
    return [bool] $current
}


function Get-VendoredPyVer([string] $dir, [string] $role) {
    <#
        The Python minor version the vendored lib\ at $dir was built for, after
        checking it is one vendor.ps1 actually produced.

        Here rather than in each caller because package.ps1 and
        bundle-client.ps1 both stage a lib\ into something a person installs,
        and both of these refusals are load-bearing: PYVER is what lets
        applaunch.py name the Python to install instead of failing inside an
        import (rule 13), and a stray .exe is the unsigned binary source mode
        exists to keep out (rule 12). A refusal written down twice is how one
        of the two copies comes to be relaxed.
    #>
    if (-not (Test-Path $dir)) {
        Fail "no vendored dependencies at $dir`n    run: .\vendor.ps1 -Role $role -Clean"
    }
    $pyverFile = Join-Path $dir "PYVER"
    if (-not (Test-Path $pyverFile)) {
        Fail ("$dir has no PYVER stamp - it was not produced by vendor.ps1.`n" +
              "    applaunch.py needs it to refuse a lib built for another Python`n" +
              "    instead of failing inside an import. Re-run vendor.ps1.")
    }
    $stray = @(Get-ChildItem $dir -Recurse -File -Include *.exe -ErrorAction SilentlyContinue)
    if ($stray) {
        Fail ("$dir contains executables, which source mode exists to avoid:`n    " +
              (($stray | ForEach-Object { $_.FullName.Substring($dir.Length + 1) }) -join "`n    ") +
              "`n`n    re-run vendor.ps1, which removes them.")
    }
    return (Get-Content -Raw $pyverFile).Trim()
}


function Get-CertFingerprint {
    <#
        SHA-256 over the certificate's DER bytes - the same value the Server
        GUI's SSL Certificate dialog shows, the client's own first-contact
        prompt shows (ADR-0010), and X509Certificate2.GetCertHashString('SHA256')
        returns, which is the line update.ps1 prints for checking one against
        the server. Four things saying one number is the whole point of it.

        Not Get-FileHash, and not certutil -hashfile: both hash the PEM's own
        text, which is a different number that looks equally plausible and
        matches none of the four. Two encodings of one certificate disagree on
        it as well. A file holding a chain is measured at its first block, the
        leaf - the one a client is actually presented with.

        Shared because package.ps1 prints the fingerprint of a certificate it
        could not verify before shipping, and update.ps1 and install-iis.ps1
        each print both fingerprints when something is about to replace the
        installed one. That is one question asked in three places, and a second
        spelling of it would let them answer differently about the same file.

        -Der is that third caller's door: install-iis.ps1 is holding a
        certificate out of Cert:\LocalMachine\My and no file, the PEM it is
        warning about not being written yet. The DER bytes are what this
        measures either way, so the two ways in meet on the same line rather
        than being two implementations. That caller cannot use
        GetCertHashString('SHA256') for it - that overload is .NET Framework
        4.8 and Windows Server 2019 ships 4.7.2, where a correct install would
        die on a missing method while printing a warning.
    #>
    [CmdletBinding(DefaultParameterSetName = "Path")]
    param(
        [Parameter(Mandatory = $true, ParameterSetName = "Path", Position = 0)]
        [string] $Path,
        [Parameter(Mandatory = $true, ParameterSetName = "Der")]
        [byte[]] $Der
    )

    if ($PSCmdlet.ParameterSetName -eq "Path") {
        $pem = Get-Content -Raw $Path
        $b64 = [regex]::Match($pem, '(?s)-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----').Groups[1].Value
        if (-not $b64) { return "(not a PEM certificate)" }
        $Der = [Convert]::FromBase64String(($b64 -replace '\s', ''))
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $sha.ComputeHash($Der) } finally { $sha.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString("X2") }) -join ':')
}

function Invoke-PinnedRequest {
    <#
        An https request this machine can actually complete against its own
        self-signed certificate, by accepting exactly the certificate in
        $PinPath and nothing else.

        The two scripts here that probe a server they just installed or updated
        could not: install-iis.ps1 -SelfSigned mints into Cert:\LocalMachine\My
        and nothing in tools\ or in any runbook puts a copy in LocalMachine\Root,
        so the chain is untrusted on the machine that minted it, and Windows
        PowerShell 5.1 has no -SkipCertificateCheck. Every attempt threw "Could
        not establish trust relationship for the SSL/TLS secure channel":
        install-iis.ps1 warned "/health did not answer" on every correct install,
        and update.ps1 read that as a bad build and rolled a good update back
        over an already-migrated database.

        This is not rule 1 turned off. Rule 1 is a client deciding whether to
        trust a server; these two are asking this machine's own certificate for
        /health and /version, carrying no credential - and both hold the file to
        pin against, which is the very file the clients pin (GET /cert serves
        it). Accepting one certificate is stricter than the default chain check,
        not looser: a CA-issued certificate for the right name is refused here
        unless it is that one.

        With no pin - a plain http:// url, or no such file - the request is made
        with default validation, which is what a CA-issued certificate needs and
        is the behaviour every caller had before.

        A compiled callback rather than a scriptblock: .NET invokes it on a
        thread with no runspace, so a scriptblock throws "There is no Runspace
        available" and surfaces as "The underlying connection was closed", which
        reads as the server's fault (package.ps1 says the same thing about the
        same trap). It is set on the request rather than on ServicePointManager,
        which is process-wide; the protocol set is process-wide and is put back.

        Never throws for a request that failed - both callers loop over
        attempts, and an exception would only be caught and thrown away.
        Answers StatusCode 0 with Error saying why, and Presented carrying the
        fingerprint the server actually offered, because a pin refusal and a
        server that is not there are different things to be told.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $Url,
        [string] $PinPath,
        [int]    $TimeoutSec = 15
    )

    $pinned = $null
    if ($Url -like "https://*" -and $PinPath -and (Test-Path $PinPath)) {
        $fp = Get-CertFingerprint $PinPath
        if ($fp -match '^[0-9A-F]{2}(:[0-9A-F]{2})+$') { $pinned = $fp }
    }

    if (-not ("AmPinnedCert" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

public class AmPinnedCert {
    private readonly string _expected;
    public string Presented;
    public AmPinnedCert(string expected) { _expected = expected; }
    public RemoteCertificateValidationCallback Callback { get { return Check; } }
    private bool Check(object sender, X509Certificate cert, X509Chain chain,
                       SslPolicyErrors errors) {
        if (cert == null) { return false; }
        using (SHA256 sha = SHA256.Create()) {
            byte[] h = sha.ComputeHash(cert.GetRawCertData());
            StringBuilder sb = new StringBuilder();
            foreach (byte b in h) {
                if (sb.Length > 0) { sb.Append(':'); }
                sb.Append(b.ToString("X2"));
            }
            Presented = sb.ToString();
        }
        return string.Equals(Presented, _expected, StringComparison.OrdinalIgnoreCase);
    }
}
"@
    }

    $pin   = $null
    if ($pinned) { $pin = New-Object AmPinnedCert $pinned }
    $code  = 0
    $text  = ""
    $err   = $null
    # 5.1's default protocol set predates TLS 1.2, which is all IIS negotiates.
    $savedProtocol = [Net.ServicePointManager]::SecurityProtocol
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $req = [Net.HttpWebRequest]::CreateHttp($Url)
        $req.Timeout          = $TimeoutSec * 1000
        $req.ReadWriteTimeout = $TimeoutSec * 1000
        if ($pin) { $req.ServerCertificateValidationCallback = $pin.Callback }
        $resp = $req.GetResponse()
        try {
            $code = [int] $resp.StatusCode
            $sr = New-Object IO.StreamReader($resp.GetResponseStream())
            try { $text = $sr.ReadToEnd() } finally { $sr.Dispose() }
        } finally { $resp.Close() }
    } catch {
        $err = $_.Exception.Message
    } finally {
        [Net.ServicePointManager]::SecurityProtocol = $savedProtocol
    }

    $presented = $null
    if ($pin) { $presented = $pin.Presented }
    if ($err -and $pinned -and $presented -and $presented -ne $pinned) {
        $err = "the server presented a certificate other than $PinPath ($err)"
    }
    return [pscustomobject]@{
        StatusCode = $code
        Content    = $text
        Error      = $err
        Pinned     = $pinned
        Presented  = $presented
    }
}

function Get-BoundCertThumbprint {
    <#
        The thumbprint IIS actually has bound to $SiteName's https port, read
        straight out of IIS:\SslBindings -- not out of ssl_cert.pem, which is a
        copy of a fact and not the fact itself once the two can drift. Local
        only: no network call, so update.ps1 can call this under -WhatIf.

        $null for a site with no https binding, or a binding IIS:\SslBindings
        does not carry an entry for -- both read as "nothing to reconcile"
        rather than a thrown error, since the caller's answer to either is the
        same: there is no live binding to compare ssl_cert.pem against.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $SiteName
    )

    $binding = Get-WebBinding -Name $SiteName -Protocol https -ErrorAction SilentlyContinue |
               Select-Object -First 1
    if (-not $binding) { return $null }
    if ($binding.bindingInformation -notmatch '^[^:]*:(\d+):') { return $null }
    $port = $Matches[1]

    $ssl = Get-Item "IIS:\SslBindings\0.0.0.0!$port" -ErrorAction SilentlyContinue
    if (-not $ssl) { return $null }
    return $ssl.Thumbprint
}

function Test-FirstTimeCertSetup {
    <#
        Is this the one run that may mint a certificate nobody asked for -- a
        first-time setup, where no certificate source was given, $InstallDir
        holds no ssl_cert.pem, and $SiteName has nothing bound to its https
        port.

        All three, because an existing certificate must never be regenerated:
        every client pins ssl_cert.pem and fails closed against anything else
        (rule 1), so a re-run that minted a fresh one strands the whole fleet
        in the middle of routine maintenance, with nothing said at the time.
        The pem and the binding are asked about separately rather than one
        standing in for the other -- a site bound to a certificate whose pem
        somebody deleted is still an install with a certificate, and a pem
        beside a site that has not been bound yet is still a file clients may
        already hold.

        Here rather than inline in install-iis.ps1, which is its only caller,
        for what that buys: this is the decision in that script whose wrong
        answer costs the most, and the script itself stands up IIS and cannot
        be run by a gate, while this file is the one every script here
        dot-sources -- and so the one a harness can dot-source too.
        deploy-checks.ps1 drives all four states over it with
        Get-BoundCertThumbprint stubbed.

        $SourceGiven is a [bool] rather than a [switch] for trap three's
        reason, the same one Resolve-Switch takes one for.
    #>
    param(
        [Parameter(Mandatory = $true)][string] $InstallDir,
        [Parameter(Mandatory = $true)][string] $SiteName,
        [bool] $SourceGiven = $false
    )

    if ($SourceGiven) { return $false }
    if (Test-Path (Join-Path $InstallDir "ssl_cert.pem")) { return $false }
    if (Get-BoundCertThumbprint $SiteName) { return $false }
    return $true
}

function Import-CertPair {
    <#
        Puts $CertPath and $KeyPath -- the install directory's own
        ssl_cert.pem and ssl_key.pem, the file GET /cert serves and the key
        that never leaves this machine -- into Cert:\LocalMachine\My as one
        certificate carrying its private key, so the app pool identity can
        present it. Returns the thumbprint either way.

        Skips the import when a certificate with that DER's thumbprint is
        already in LocalMachine\My with a private key attached -- "if not
        already there" from the ticket -- so a reconcile that runs more than
        once does not reimport the same key on every health-check retry.

        Reads the private key as PKCS#8 ("BEGIN PRIVATE KEY") or PKCS#1
        ("BEGIN RSA PRIVATE KEY"), both of which RSA.ImportPkcs8PrivateKey and
        RSA.ImportRSAPrivateKey read under .NET Framework 4.7.2 -- Windows
        Server 2019's version -- unlike CopyWithPrivateKey's PFX-round-trip
        cousins that need 4.8. The certificate and the key are joined with
        CopyWithPrivateKey and then exported to PFX and reimported with
        MachineKeySet + PersistKeySet, because a key attached only in memory
        is not one another process -- the app pool identity, in a later
        request -- can find again.
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string] $CertPath,
        [Parameter(Mandatory = $true)][string] $KeyPath
    )

    if (-not (Test-Path $CertPath)) { throw "Certificate not found: $CertPath" }
    if (-not (Test-Path $KeyPath))  { throw "Private key not found: $KeyPath" }

    $certPem = Get-Content -Raw $CertPath
    $certB64 = [regex]::Match($certPem, '(?s)-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----').Groups[1].Value
    if (-not $certB64) { throw "$CertPath is not a PEM certificate." }
    $certDer = [Convert]::FromBase64String(($certB64 -replace '\s', ''))
    $leaf = New-Object Security.Cryptography.X509Certificates.X509Certificate2 (, $certDer)

    $already = Get-ChildItem Cert:\LocalMachine\My |
               Where-Object { $_.Thumbprint -eq $leaf.Thumbprint -and $_.HasPrivateKey }
    if ($already) { return $already.Thumbprint }

    $keyPem = Get-Content -Raw $KeyPath
    $pkcs8 = [regex]::Match($keyPem, '(?s)-----BEGIN PRIVATE KEY-----(.*?)-----END PRIVATE KEY-----')
    $pkcs1 = [regex]::Match($keyPem, '(?s)-----BEGIN RSA PRIVATE KEY-----(.*?)-----END RSA PRIVATE KEY-----')
    $rsa = [Security.Cryptography.RSA]::Create()
    if ($pkcs8.Success) {
        $keyDer = [Convert]::FromBase64String(($pkcs8.Groups[1].Value -replace '\s', ''))
        [void] $rsa.ImportPkcs8PrivateKey($keyDer, [ref] 0)
    } elseif ($pkcs1.Success) {
        $keyDer = [Convert]::FromBase64String(($pkcs1.Groups[1].Value -replace '\s', ''))
        [void] $rsa.ImportRSAPrivateKey($keyDer, [ref] 0)
    } else {
        throw "$KeyPath is not a PEM private key."
    }

    $withKey = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey($leaf, $rsa)
    $flags = [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::MachineKeySet -bor
             [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::PersistKeySet -bor
             [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable
    $pfxBytes = $withKey.Export([Security.Cryptography.X509Certificates.X509ContentType]::Pfx, "")
    $imported = New-Object Security.Cryptography.X509Certificates.X509Certificate2 (, $pfxBytes), "", $flags

    if ($PSCmdlet.ShouldProcess($imported.Thumbprint, "Import into LocalMachine\My")) {
        $store = New-Object Security.Cryptography.X509Certificates.X509Store("My", "LocalMachine")
        $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        try { $store.Add($imported) } finally { $store.Close() }
    }
    return $imported.Thumbprint
}

function Set-SiteCertificate {
    <#
        Rebinds $SiteName's https port to $Thumbprint, mirroring
        install-iis.ps1's own SSL binding: resolve the port off the site's
        https binding rather than assuming one, remove whatever
        IIS:\SslBindings\0.0.0.0!<port> currently holds, and bind the
        certificate in Cert:\LocalMachine\My with that thumbprint in its
        place. Throws naming the site or the certificate when either is
        missing, so a caller's try/catch is what turns that into the ordinary
        health-check failure and rollback -- this function does not decide
        what happens next.
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string] $SiteName,
        [Parameter(Mandatory = $true)][string] $Thumbprint
    )

    $binding = Get-WebBinding -Name $SiteName -Protocol https -ErrorAction SilentlyContinue |
               Select-Object -First 1
    if (-not $binding) { throw "Site $SiteName has no https binding to rebind." }
    if ($binding.bindingInformation -notmatch '^[^:]*:(\d+):') {
        throw "Could not read the port out of $SiteName's https binding."
    }
    $port = $Matches[1]

    $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $Thumbprint }
    if (-not $cert) { throw "No certificate with thumbprint $Thumbprint in LocalMachine\My." }

    if ($PSCmdlet.ShouldProcess("0.0.0.0:$port", "Bind certificate $Thumbprint")) {
        $existing = Get-Item "IIS:\SslBindings\0.0.0.0!$port" -ErrorAction SilentlyContinue
        if ($existing) { Remove-Item "IIS:\SslBindings\0.0.0.0!$port" -Force }
        New-Item -Path "IIS:\SslBindings\0.0.0.0!$port" -Value $cert | Out-Null
    }
}
