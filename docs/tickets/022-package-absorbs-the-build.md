# 022 - package.ps1 absorbs the build, and stops making two copies of everything

**Type:** refactor · **Depends on:** nothing · **Found by:** asked for directly

## Finding

The build is two tools in two languages with one seam between them: `build.bat` (89
lines of batch) makes the exes, `tools/package.ps1` (651 lines of PowerShell) turns
them into a release, and `-Build` bridges them by shelling out to the `.bat`. Everything
`package.ps1` knows - `deploy.json`, `OutputDir`, the version agreement across the four
sources, the private-key refusals - stops at that seam, so the half of the pipeline that
actually produces the payload is the half none of it can see.

**And the seam costs a copy of every exe.** `build.bat` step 6 copies all four out of
`dist\` into `output\` because that is the only way a batch file can hand PowerShell a
directory it agreed on. Both directories are ~246 MB and hold the same four files.
PyInstaller writes wherever `--distpath` says, so the copy exists for no reason but the
language boundary.

Measured on this machine, the build tree holds ~740 MB across four kinds of duplicate:

| what | size | why |
|---|---|---|
| the four exes in `dist\` **and** `output\` | ~246 MB each | `build.bat` step 6. **This one is the script's own.** |
| `AssetManager-2.3.0.zip` in `output\` as well as `packages\` | 244 MB each, and the two differ | not a default run - `package.ps1:628` writes only to `PackageDir` - so a `-PackageDir output` run or a hand copy |
| `dist\*_dist` | ~246 MB | orphans nothing names |
| `packages\NotifierApp-2.3.0\` | - | `bundle-client.ps1`'s staging left beside its own zip |

None of it ever reached a package: staging is a whitelist (`$Exes`, `$Extras` at
`package.ps1:160`), not a directory sweep. This is wasted disk and a confusing tree, not
a corrupt release.

## Scope

`tools/package.ps1`, and `build.bat` is deleted.

1. **Port the seven build steps in** as a function `package.ps1` calls where `-Build`
   currently invokes the `.bat`. Same PyInstaller invocations, same `--hidden-import
   win32timezone`, same `--uac-admin` on the installer, same public-certificate-only
   `--add-data` rule. `--distpath` points at `OutputDir`, so step 6's copy goes and
   `dist\` stops being written at all.

2. **`-Component server|client|all`**, defaulting to `all`. `server` builds
   `AssetServer.exe`; `client` builds `StorekeeperApp.exe` and `NotifierApp.exe`.
   `AssetManager_Setup.exe` bundles all three by `--add-data`, so it is built on `all`
   and on neither of the others - a partial installer would be an installer that cannot
   install what it offers.

3. **`-Component client` calls `bundle-client.ps1`** rather than absorbing it - it
   already takes `-CertPath`, `-PackageDir` and `-ConfigPath`, and keeping it a file of
   its own keeps rule 12's blanket `.exe` refusal where it is rather than folding it
   into a script whose whole job is making exes. Its `-App` is mandatory and single, so
   a client run calls it twice. **The certificate `package.ps1` resolved is passed
   through**, so a `-SelfSigned` run ships the same certificate to the clients that it
   staged for the server: two bundles pinned to a certificate the server does not bind
   is the failure that has no channel left to correct it.

4. `build.bat` is deleted and every reference to it moves in the same commit.

**`-SelfSigned` is not touched.** It already mints, writes `ssl_key.pem` beside the
package and never inside, and prints the fingerprint. It stays a switch and does not
become a prompt on a missing certificate: what makes it safe is that somebody decided to
carry that key to the server *before* starting a ten-minute build, and a y/n at the end
of one is answered by reflex. `package.ps1` also runs where nobody can answer, which is
what `Test-CanPrompt` exists for. Ticket 001 settled this.

## Not in this ticket

- **Rule 14 still holds and is not being weakened.** The exe steps are not retired, they
  move; `build.bat`'s own *name* is what goes. The rule's sentence needs rewording to
  name where the steps now live, not deleting.
- The stale artefacts above are chores, not code: `dist\*_dist`, the `output\` zip and
  the unzipped `NotifierApp-2.3.0\`. Deleting them changes nothing this ticket builds.
- `packages\ssl_key.pem` is a real private key awaiting collection, not rubbish. It is
  removed by whoever binds it on the server, not by this work.

## Cascade

All in the same commit, or `cascade-audit.py` goes red - it holds every file in `tools\`
against the table it is in, every path the docs name, and the `.ps1` files' ASCII-ness:

- `CLAUDE.md`: the `package.ps1` and `bundle-client.ps1` tooling sections, the
  "Build & Deploy" block that says to run `build.bat`, both "Pushing an update"
  sequences, rule 14's wording, and the two architecture-table rows ending "so
  `build.bat` needs no entry for it".
- `docs/CODING_STANDARDS.md`, `docs/runbooks/iis-cutover.md`,
  `docs/runbooks/source-mode.md`, `tools/deploy.example.json`, and the comments naming
  `build.bat` in `tools/update.ps1`, `tools/bundle-client.ps1`, `tools/_devtools.py`,
  `common.py` and `installer.py`.
- **ASCII.** `build.bat` carries an em dash on lines 3, 7 and 59. A `.ps1` may not: 5.1
  reads a BOM-less file as cp1252 and the trailing byte becomes a smart quote.

## Verification

`cascade-audit.py` exits 0 on the docs. The build itself is checked by running it:
`-Component server`, `-Component client` and the default, each against what lands in
`OutputDir` and `PackageDir` - and `dist\` is not created. `package.ps1 -Build` must
still produce a package whose manifest hashes `update.ps1` will verify.
