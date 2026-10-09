# 064 - The narrow-band leg settled on two identical reads

**Type:** bug · **Depends on:** - · **Found by:** re-deriving the counts #214 recorded · **Issue:** [#239](https://github.com/HaithamEldesouky/AssetManager/issues/239) · **Status:** closed and merged, `f3cf39b`

This file is a record of a closed ticket rather than open work. It is kept because the
measurements in it were the reason two other recorded measurements got re-derived, and
because the question in the last section is still open and is tracked nowhere else.

## What was seen

`tools/server_checks/console.py`'s group `nothing on this window is cut off at a narrow
size` has a leg at 1.75x scaling and 940px width. It reported:

```
1.75x at 940px: 1 block(s) on the band were given less than they asked for, the worst
by 26px - a block `pack` shrank is a Server URL with its port cut off, and measures
from outside exactly like one that fit
```

It came and went between runs of unchanged code. Measured 2026-09-22 on `main` at
`1688e82`, every row the same commit and the same machine:

| run | `AM_GATE_OFFSCREEN` | result |
|---|---|---|
| `--group console` | unset | green, twice |
| `--group console` | `=1` | **RED**, twice |
| whole suite, serial | `=1` | green, 236 groups / 2626 assertions |
| whole suite, 8 shards | `=1` | **RED**, twice (once this leg, once `tls.py`) |
| `gate.py --all` | `=1` | green, green, **RED** |

`gate.py` sets `AM_GATE_OFFSCREEN=1` on every run and shards the server suite across
cores, so both red shapes are what a gate run actually does. `land.py` refuses a red
gate, which is correct and is what made this block landing.

## What it turned out to be, and what this ticket got wrong

This ticket was filed reading that matrix as **the neighbours**: the set of groups that
ran ahead of the leg in the same interpreter, since `--group console` runs none, the
whole suite runs five modules first, and a shard runs an arbitrary subset. That reading
was wrong, and the title it produced was wrong with it.

Re-measuring the band itself found no variance in it at all: every settled read at that
leg is bit-identical, and neither `AM_GATE_OFFSCREEN` nor the set of preceding groups
moves a number. What moved was the **settle**. `resize()` ended on two identical reads,
and two is not enough to say a layout has stopped - a half-settled band reads a few
pixels short and then agrees with itself once before the children finish. Requiring a
third identical read costs one more 60ms pass and makes the leg repeatable.

Both of the readings this ticket weighed were therefore half-right in the wrong place.
The red read was not true of the window and not disturbed by neighbours; it was a true
read of a window that had not finished laying out. The precedent cited for reading 1 -
#204 and #205, where unsettled reads intermittently missed a clipped Copy URL and the
green runs were the wrong ones - was the right precedent pointing at the wrong half: the
same defect, settling, with the colours swapped.

The fix also made the leg report the size of the band's margin rather than only its sign,
so 28px of room and 285px of room no longer print the same line.

- No assertion was added or removed; the serial count is unchanged.
- Driven at the failure: with a 20-character hostname reaching the window, the
  1.75x/940px leg still fails, 52px short.
- `gate.py --all` green twice on top of it.

`fix/stale-assertion-counts` - the local branch this ticket named below as conflicting by
construction - landed with it, which is where the re-derived counts (872/68 -> 927/69 for
the client, 2615/234 -> 2626/236 for the server) went.

## Still open: the client `SHARD_CAP`

Nothing closed this, and no issue carries it. It is written here because this is the only
place it is written down.

`SHARD_CAP = {"client": 4}` rests on a measurement that no longer reproduces. Measured
2026-09-22, same machine, `AM_GATE_OFFSCREEN=1`, `client-checks.py --shard i/8` run
directly so `gate.py`'s cap does not apply:

| tree | groups | assertions | result |
|---|---|---|---|
| `main` at `1688e82` | 69 | 927 | all green |
| same + the `ticket-205` Dismiss fix | 69 | 928 | all green |

The cap exists because #194/#201 measured eight shards **failing both popup groups**,
with four green twice. They pass at eight today, with and without that change.

That leaves a matched pair pointing opposite ways: the server was uncapped on a
measurement (#214) that said 8 shards were green and went red, and the client is capped
on a measurement that said 8 shards were red and is now green. Two stale measurements
moving in opposite directions argue against one environmental cause - and the settle
defect above is a better explanation of the server half than load ever was.

A lead rather than a conclusion for the client half: #205 replaced fixed `pump()` calls
with `pump_until(...)` waits on a condition, which is the change that would stop
timer-sensitive groups caring about contention. If so the cap has been dead weight since
#205 landed, and lifting it cuts the client suite from ~2m00s toward its 8-shard time on
every gate run.

Not a change to make on this evidence - one green run each way is thinner than
`gate.py`'s own comment demands. Whoever picks it up re-derives the counts rather than
copying the ones above forward, per `CLAUDE.md`'s rule for a documented measurement.

## Also not closed by this

`tls.py`'s `a quiet tick paints nothing` failed once under 8 shards and is green run
alone with the flag set. That one was never diagnosed. It is its own ticket if it
recurs, and the settle defect above is the first thing to look for.
