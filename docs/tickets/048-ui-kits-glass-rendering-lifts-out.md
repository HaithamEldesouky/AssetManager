# 048 - ui_kit.py's glass rendering lifts out

**Type:** refactor · **Depends on:** nothing (sequence after 044, 045 for the cascade line) · **Found by:** architecture review, Sep 2026 · **Issue:** [#222](https://github.com/HaithamEldesouky/AssetManager/issues/222)

## Finding

`ui_kit.py` is 2,940 lines. One contiguous region, `ui_kit.py:1767-2940` - the rest of the
file, to end of file - is the glass rendering: colour math, the ground and panel painters,
`Surface`, `ImageBank`, and icon generation. Verified by grep:

- `GLASS_RADIUS`/`GLASS_BLUR`/`GLASS_ALPHA`/`GLASS_EDGE`, `GLOW_STRENGTH`, `GROUND_ANGLE` -
  `ui_kit.py:1767-1772`.
- colour helpers (`rgb`, `hexs`, `mix`, `lift`, `sink`, `_ramp`, `_mask`, `_dither`) -
  `1781-1905`.
- `gradient`, `glow`, `frost`, `sample`, `photo` - `1906-2046`.
- `class ImageBank` - `2047`.
- `_ground_cached`/`_ground_keep`/`ground`/`panel` - `2105-2205`.
- `class Surface` - `2206`.
- icon generation (`_icon_gradient` through `set_window_icon`) - `2657-2940`, to end of
  file.

2940 - 1767 + 1 = 1,174 lines - the "~1,175" this ticket was filed against, confirmed
rather than copied forward. Nothing in the region reaches back into the rest of
`ui_kit.py` except the module's own imports (`Image`/`ImageDraw`/`ImageTk` from Pillow,
guarded the way `ui_kit.HAS_PIL` already is) - `Theme` (`ui_kit.py:705`), `TOKENS`/`DARK`,
`fit`, `ScrollRegion` and the rest of the palette-and-sizing half of the file stay put and
are untouched by this move.

**Every caller says `ui_kit.Surface`.** `server_gui.py`, `notifier_app.py` (and, after 044,
`notifier_remote.py`), `storekeeper_app.py` (and, after 045, `storekeeper_export.py`) all
draw through `ui_kit.Surface`, `ui_kit.ground`, `ui_kit.panel`, `ui_kit.ImageBank`,
`ui_kit.app_icon` and `ui_kit.set_window_icon` - 22 call sites across the four apps in the
current tree. Moving the region wholesale and leaving no re-export would break every one of
them; the module keeps the name.

## Scope

One new module, `ui_glass.py`, beside `ui_kit.py`.

1. **Move `ui_kit.py:1767-2940` verbatim** into `ui_glass.py`.
2. **`ui_kit.py` re-exports every name a caller reaches through `ui_kit.<name>` today**:
   `from ui_glass import (GLASS_RADIUS, GLASS_BLUR, GLASS_ALPHA, GLASS_EDGE,
   GLOW_STRENGTH, GROUND_ANGLE, rgb, hexs, mix, lift, sink, gradient, glow, frost, sample,
   photo, ImageBank, ground, panel, Surface, app_icon, set_window_icon, ...)` - grep every
   `ui_kit.<name>` call site across the four apps before finalising this list; a name
   reached once and left off the re-export is a silent `AttributeError` the moment that one
   window opens.
3. **No caller changes.** `ui_kit.Surface` still resolves, because `ui_kit.py` imports it
   back - the same shape `server.py` uses for `server_cert`'s and `server_gui`'s exports,
   one level simpler since `ui_kit.py` is imported normally everywhere (no
   `runpy.run_path` entry point owns it the way `server.py`/`notifier_app.py`/
   `storekeeper_app.py` do), so a flat `from ui_glass import ...` needs no `bind()`.

## Not in this ticket

- Any change to how glass is painted, what a colour resolves to, or icon generation's
  output. A move, not a redesign.
- `Theme`, `TOKENS`/`DARK`, `fit`, `ScrollRegion`, or anything else in the
  palette-and-sizing half of `ui_kit.py` (lines 1-1766). Untouched.
- Deleting the re-export once callers could theoretically import `ui_glass` directly. Every
  caller says `ui_kit.Surface` today and stays saying it; a follow-up ticket that migrates
  call sites to `ui_glass.Surface` directly is a separate, much larger change touching four
  apps' worth of call sites, and is not implied by this one.

## Cascade

- `CLAUDE.md` "The files" table - gains a `ui_glass.py` row; the `ui_kit.py` row's
  description narrows to the palette and sizing kept there.
- `docs/reference/architecture.md` - the same, in full. **`ticket-workflow.md` "Two
  tickets that cascade to the same line" names this exact row as ~1,978 characters on one
  line** - re-measure once written rather than trusting that number, and sequence this
  ticket after 044 and 045 since both touch nearby rows in the same table (`notifier_app.py`
  and `storekeeper_app.py`'s own descriptions), the same reason 035/036 were sequenced over
  one `package.ps1` line.
- `docs/CODING_STANDARDS.md` "Where code goes" - gains the module.
- `tools/package.ps1:148` `$SourceFiles` - gains `ui_glass.py` on the server side (the
  Server GUI imports `ui_kit`, so its own package needs `ui_glass.py` beside it).
- `tools/bundle-client.ps1:125` `$Payload` - gains `ui_glass.py` alongside `ui_kit.py`,
  since every client stages `ui_kit.py` today and would silently import a module that
  cannot find its own half if `ui_glass.py` is missing beside it.
- `installer.py:49` `SOURCE_FILES` - every app entry that lists `ui_kit.py` gains
  `ui_glass.py` beside it.
- `tools/client-checks.py`'s staging block and `tools/server-checks.py:141`'s staging
  tuple - both copy `ui_kit.py` into their staged tree; both need `ui_glass.py` copied
  alongside it or the staged import fails.
- `tools/dev-run.ps1:283` `$ClientShared = @("common.py", "ui_kit.py",
  "client_update.py")` - gains `ui_glass.py`.
- `tools/gate.py` `MAP` (`tools/gate.py:78`) - the existing
  `r"^(common|ui_kit)\.py$"` row (tagged `("server", "client")`) becomes
  `r"^(common|ui_kit|ui_glass)\.py$"`, or an edit to `ui_glass.py` runs no gate.
- `tools/cascade-audit.py:1462` `BESIDE_MODULES` includes `ui_kit.py`'s module-level
  assignments; if any of `GLASS_RADIUS`/`GLOW_STRENGTH`/`GROUND_ANGLE` are read by name
  from that list, point the read at `ui_glass.py` instead once they move, or the check
  passes by finding nothing.
- `tools/cascade-audit.py:1601` `_UIKIT = ast.parse(read('ui_kit.py'))` - walked for
  `TOKENS`/`DARK` (`1603`), the `Theme.__init__` `_bind` seed (`1613`), `FAMILIES`
  (`1662`), and the font seed (`1677`). All four read names that stay in `ui_kit.py` after
  this move (`Theme` at line 705, `TOKENS`/`DARK`/`FAMILIES` in the palette half) -
  verified by line number against the moved region (1767-2940), so **none of these four
  checks need to change**. Confirm this is still true against the tree at the time this
  ticket is worked, rather than trusting it here; a check added between now and then could
  reach into the moved region without this ticket's author knowing to look.

## Verification

- `ast.parse()` both files.
- `py -3.12 tools/gate.py` - the gates this diff can reach.
- Open one window from each app that draws glass (Server GUI's own chrome, a Notifier
  popup, the Storekeeper's main window) and confirm the frosted panel, gradient ground and
  window icon all render unchanged.
- `py -3.12 tools\server-checks.py` and `py -3.12 tools\client-checks.py` green.

## How it landed

`ui_kit.py:1758-2932` - the depth-layer banner through `set_window_icon`'s last line,
1,175 lines - is `ui_glass.py`, which is 1,229 with its own header and imports.
`ui_kit.py` drops from 2,940 lines to 1,774. The Finding names 1767-2940 and measures
1,174; it is the same region, and 1,175 rather than 1,174 because the section banner
came with it, while `__all__` and the two blank lines above it stayed behind - that list
is `ui_kit`'s own public surface, not the glass's.

**It reaches back for one name, and the Finding was wrong that it reaches back for
none.** Built with a `symtable` sweep rather than by eye, the way #219's was: every
top-level name `ui_kit.py` binds was collected and "does this region resolve NAME as a
global" was answered the way Python's own scoping answers it. Nine came back. Eight are
imports - `base64`, `io`, `Image`, `ImageChops`, `ImageDraw`, `ImageFilter`,
`ImageMath`, `HAS_PIL` - and the kept half reads not one of them (`sys` is the only
import it still uses), so all eight moved outright rather than being left behind as a
second copy of one decision. The ninth is `round_rect`, which `panel` draws on its
no-pillow path: a five-line canvas helper that belongs beside `Pill`, so it stays in
`ui_kit.py` and `panel` says `ui_kit.round_rect` with the `import ui_kit` **inside the
branch**. At module level it would be a cycle - `ui_kit` imports this module at the foot
of its own body, so anything that reached `ui_glass` first would be handed a half-built
`ui_kit` - and the branch it sits in is the flat fallback, which is not hot. Nothing in
the kept half reads a moved name, which the same sweep answered in the other direction
and is what made the region a region.

**No `bind()`**, which is the one way this move is simpler than #206's, #207's, #218's
and #219's. Those four could not import the module they came out of: `runpy.run_path`
runs `server.py`, `notifier_app.py` and `storekeeper_app.py` as `__main__`, so an import
would start a second server or a second tray client rather than reach the one running.
No entry point owns `ui_kit.py` - every app imports it normally - so importing it back
starts nothing, and a flat `from ui_glass import ...` is the whole of the seam.

**Every caller still says `ui_kit.Surface`.** `ui_kit.py` re-exports the 37 names the
four apps and the two gates reach through it, the list built by grepping
`ui_kit\.<name>` across every `.py`, `.ps1` and `.md` in the tree and checking each of
the 43 hits resolves on the finished module - one, `ui_kit.Flow`, is a comment in
`server_gui.py` about a class #205 deleted. Not one call site changed. `_GROUNDS` is in
the list as the same list object, not a copy, which is what keeps `client-checks.py`'s
four `del ui_kit._GROUNDS[:]` reaching the memo `ui_glass` reads.

**`HAS_PIL` moved, and that is a cascade the ticket did not name.** The flag is read
only by the moved region, so it lives with it - but both gates *write* it, 24 times in
`client-checks.py` and 9 in `server-checks.py`, to drive the no-pillow pass, and a write
to `ui_kit.HAS_PIL` after the move reaches a re-exported binding that no renderer looks
at. Those 33 sites now say `ui_glass.HAS_PIL`, with an `import ui_glass` beside the
`import ui_kit` of each of the 14 functions that hold them. Left alone this would not
have been silent - `check_the_source_mode_shortcut_carries_the_app_icon` asserts
`app_icon(64)` is `None` with pillow off and would have failed loudly - but it would
have been a gate reporting the wrong reason.

**Verbatim, and measured as such.** `git show HEAD:ui_kit.py | sed -n '1758,2932p'`
against the region of the new file diffs to exactly the `round_rect` hunk above and
nothing else. The renders are byte-identical rather than merely present: `gradient`,
`glow` and `frost` at 900x600 over the dark ground, `sample` off the frost, and
`app_icon` at 256 plain, 64 badged and 32 with a status dot, SHA-256'd under the old
file and the new, all nine the same digest, plus `mix`/`lift`/`sink`/`hexs` agreeing
string for string. The one line that changed was driven on a real `tk.Canvas` with
`ui_glass.HAS_PIL` forced off: `panel` answers the face it was given and leaves one
smoothed polygon filled `CARD` and outlined `LINE`, which is what `round_rect` drew
before.

**Cascaded:** `CLAUDE.md`'s files table and `docs/reference/architecture.md` both gain a
`ui_glass.py` row, the architecture one cut out of the `ui_kit.py` row at "It also holds
the **app icon**" so the depth-layer and icon prose moved rather than being rewritten;
`docs/CODING_STANDARDS.md`'s "Where code goes" and its headless-safety list;
`docs/reference/tooling.md`'s server-zip, client-zip, `dev-run.ps1` and `gate.py`
sentences; `tools/package.ps1`'s `$SourceFiles`, `tools/bundle-client.ps1`'s `$Payload`,
`installer.py`'s `SOURCE_FILES` for both apps, `tools/dev-run.ps1`'s `$ClientShared`,
both gates' staging blocks, `tools/gate.py`'s `MAP` row, and `cascade-audit.py`'s
`SHIPS`. `docs/agents/ticket-workflow.md`'s "two tickets that cascade to the same line"
cited 1978 and 1931 characters and told its reader to re-measure; re-measured, the
`ui_kit.py` row is 21,609 even after this move, `ui_glass.py`'s is 14,477, `common.py`'s
4,557, the longest Remote Admin bullet 11,001 and the PowerShell traps paragraph 4,330.

**Checked and deliberately not cascaded:** `cascade-audit.py`'s four `_UIKIT` walks read
`TOKENS`/`DARK` (1603 in the ticket, 1713 in the tree as worked), the `Theme.__init__`
`_bind` seed, `FAMILIES` and the font seed - all four name things in the kept half, and
no check added since the ticket was written reaches into the moved region; re-verified
against the tree rather than trusting the ticket. `BESIDE_MODULES` for #219's reason -
it reads module-level `os.path.join` assignments and the moved region has none.
`client-checks.py`'s window-forcing `allowed` map - the region calls no `lift()`,
`focus_force()` or `-topmost`. `client-checks.py`'s `APPS` - `ui_glass.py` is not an app
and has no entry point. The `dev-run.ps1` staging check derives its list from what each
**app** imports, one level, and no app imports the glass, so `ui_glass.py` is written
into `$ClientShared` with a comment saying why it cannot be derived rather than the
check being deepened - a transitive walk is a change to what that gate is, not to this
ticket. No `APP_VERSION` bump: a refactor with no behaviour change, and the release that
ships it stamps it. No new endpoint, no database column, no System Log event, no new
file written beside an app.

**Gates:** `py -3.12 tools/gate.py` is GREEN in 266s - cascade, server, client and
deploy. `server-checks.py` alone is 236 groups, 2,626 assertions, 0 skipped;
`client-checks.py` alone is 69 groups, 927 assertions, 0 skipped. The ticket's by-hand
step is what those two already drive rather than a click:
`check_the_server_window_stands_on_the_depth_layer`,
`check_the_storekeeper_stands_on_the_depth_layer`,
`check_the_notifier_stands_on_the_depth_layer` and
`check_the_installer_stands_on_the_depth_layer` each open the real window and read the
frosted panel and the gradient ground back off the screen, in both the pillow and the
no-pillow pass, and the icon groups do the same for `set_window_icon`. What was **not**
done is opening any of them on a real engineer laptop - rule 14's gate is on the
release, not on this commit.
