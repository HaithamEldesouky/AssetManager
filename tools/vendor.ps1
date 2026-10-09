<#
.SYNOPSIS
    Vendor the Python dependencies for one role into a lib\ directory.

.DESCRIPTION
    Runs `pip install --target` against requirements-<role>.txt and leaves a
    self-contained lib\ that applaunch.py puts on sys.path. Source-mode installs
    carry their dependencies rather than installing them per machine: the
    laptops have no pip and may have no route to PyPI, and vendoring is what
    lets the package manifest hash the dependencies along with the code.

    Two things this does beyond running pip:

      * Deletes every .exe pip leaves behind. pip --target writes console-script
        wrappers (pip.exe, f2py.exe and friends) into the target directory, and
        those are exactly the unsigned, no-reputation executables that source
        mode exists to stop shipping. Shipping one inside lib\ would defeat the
        whole exercise quietly.

      * Writes lib\PYVER with the Python minor version used. The vendored wheels
        are not portable across minor versions - pillow and charset_normalizer
        carry compiled cp3xx extensions - so applaunch.py compares this against
        the running interpreter and says which Python to install instead of
        failing inside an import.

    What remains is pure Python plus the .pyd extension modules that pillow and
    charset_normalizer legitimately need. Those are DLLs, not executables, and
    the phase-1 spike recorded no Defender or ASR event for them; see
    docs/it-asr-and-signing-request.md.

.PARAMETER Role
    server or client. Selects requirements-<role>.txt at the repo root.

.PARAMETER OutDir
    Where to write the lib directory. Defaults to lib-<role>\ in the repo root.
    tools/bundle-client.ps1 and package.ps1 copy from there into a package as
    plain lib\.

.PARAMETER Python
    The interpreter to vendor with. Defaults to whatever `python` resolves to.
    This decides the cp3xx tag baked into the compiled wheels, so it must be the
    same minor version the target machines will run.

.PARAMETER Clean
    Delete OutDir first. Without it pip installs over whatever is there, which
    leaves the previous pins in place alongside the new ones.

.EXAMPLE
    .\vendor.ps1 -Role client -Clean
.EXAMPLE
    .\vendor.ps1 -Role server -Python C:\Python312\python.exe -Clean
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("server", "client")]
    [string] $Role,

    [string] $OutDir,
    [string] $Python = "python",
    [switch] $Clean
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Info ($m) { Write-Host "  $m" }
function Warn ($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Step ($m) { Write-Host "`n[*] $m" -ForegroundColor Cyan }
function Fail ($m) { Write-Host "`n[X] $m" -ForegroundColor Red; exit 1 }

# -- Inputs ------------------------------------------------------------
Step "Checking inputs"

$reqFile = Join-Path $Root "requirements-$Role.txt"
if (-not (Test-Path $reqFile)) { Fail "no such requirements file: $reqFile" }
if (-not $OutDir) { $OutDir = Join-Path $Root "lib-$Role" }

# Resolved before it is invoked rather than checked after, because
# $ErrorActionPreference is Stop: a name that is not on PATH raises a
# terminating CommandNotFoundException at the & below, so the refusal under
# it never ran for the case it was written for. What the operator got was
# PowerShell's own "The term 'python' is not recognized", which names
# neither -Python nor the role being vendored. install-iis.ps1, dev-run.ps1
# and package.ps1 all ask Get-Command first, for this reason. The exit-code
# check below stays: it is for an interpreter that is there and does not run.
$pyCmd = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Fail ("cannot find the interpreter '$Python' - pass -Python with the full`n" +
          "    path to python.exe")
}
$Python = $pyCmd.Source

$pyVersion = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>&1)
if ($LASTEXITCODE -ne 0) {
    Fail "cannot run '$Python' - pass -Python with the full path to python.exe.`n    $pyVersion"
}
$pyVersion = "$pyVersion".Trim()
$pyPath = (& $Python -c "import sys; print(sys.executable)").Trim()

Info "role       : $Role"
Info "python     : $pyVersion  ($pyPath)"
Info "outDir     : $OutDir"

# -- Clean ------------------------------------------------------------
if (Test-Path $OutDir) {
    if ($Clean) {
        if ($PSCmdlet.ShouldProcess($OutDir, "Delete the existing lib directory")) {
            Remove-Item $OutDir -Recurse -Force
            Info "removed the previous $OutDir"
        }
    } else {
        Warn "$OutDir exists and -Clean was not passed."
        Warn "pip will install over it, leaving the previous pins alongside the new"
        Warn "ones. That is almost never what you want for a release."
    }
}

# -- pip ------------------------------------------------------------
Step "Installing $Role dependencies into lib"

if (-not $PSCmdlet.ShouldProcess($OutDir, "pip install --target from requirements-$Role.txt")) {
    Info "would run: $Python -m pip install --target $OutDir -r $reqFile"
    return
}

# --no-compile: the .pyc files are regenerated on the target machine anyway, and
# they would otherwise be hashed into the manifest while carrying the build
# machine's absolute paths.
& $Python -m pip install --target $OutDir -r $reqFile --upgrade --no-compile
if ($LASTEXITCODE -ne 0) { Fail "pip failed with exit code $LASTEXITCODE" }

# -- Strip executables ------------------------------------------------------------
Step "Removing executables pip left behind"

# The point of source mode. pip --target drops console-script wrappers into the
# target; every one is an unsigned binary with no reputation, which is the exact
# thing being eliminated. Nothing in lib\ is ever launched directly - applaunch
# imports from it - so removing them costs nothing.
$strays = @(Get-ChildItem $OutDir -Recurse -File -Include *.exe, *.bat, *.cmd, *.ps1 -ErrorAction SilentlyContinue)
if ($strays) {
    foreach ($f in $strays) {
        Info "removed $($f.FullName.Substring($OutDir.Length + 1))"
        Remove-Item $f.FullName -Force
    }
    Info "$($strays.Count) executable(s) removed"
} else {
    Info "none found"
}

# __pycache__ can still appear from a package that compiles at install time.
$caches = @(Get-ChildItem $OutDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue)
foreach ($d in $caches) { Remove-Item $d.FullName -Recurse -Force -ErrorAction SilentlyContinue }
if ($caches) { Info "$($caches.Count) __pycache__ director(ies) removed" }

# -- Stamp ------------------------------------------------------------
Step "Stamping the Python version"

# applaunch.py refuses to start when this does not match the running
# interpreter, because pillow's cp3xx extensions would fail inside an import
# with nothing the user could act on.
Set-Content -Path (Join-Path $OutDir "PYVER") -Value $pyVersion -Encoding ascii -NoNewline
Info "lib\PYVER = $pyVersion"

# -- Report ------------------------------------------------------------
$files = @(Get-ChildItem $OutDir -Recurse -File)
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
$pyd = @($files | Where-Object { $_.Extension -eq ".pyd" }).Count

Write-Host "`n[OK] vendored $Role dependencies" -ForegroundColor Green
Info "path       : $OutDir"
Info "files      : $($files.Count)  ($([math]::Round($bytes / 1MB, 1)) MB)"
Info "python     : $pyVersion - lib is NOT portable to another minor version"
Info ".pyd files : $pyd  (compiled extensions, expected; no .exe remain)"
