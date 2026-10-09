# 026 - Asset Model is picked from the models that exist

**Type:** feature (small) · **Depends on:** 024

## Finding

In the Lookup Sheet's asset form, **Asset Type is already a dropdown** - an editable
`ttk.Combobox` whose values are the types already in the register, with the caption saying
a new one reaches every client's dropdown. **Asset Model is a bare `tk.Entry`**
(`server.py:5164`), so the same model is typed freehand every time and the register ends up
holding `ThinkPad T14`, `Thinkpad T14` and `T14` as three models of one machine.

## What changes

Asset Model becomes the same widget as Asset Type: an **editable** combobox listing the
distinct models already in the register for the type currently selected, falling back to
every model when no type is chosen. Editable and not `readonly`, for the reason the Type
field is - a model that has never been bought before has to be typeable somewhere, and this
window is where the register grows one.

Unlike Type, a new Model is **not** confirmed with a question. A Type reaches every
client's dropdown and changes what rule 2 serves; a Model is filled into a Transaction that
sends none and reaches nothing else. Asking about it would be ceremony.

The values are re-read when the Type selection changes, so picking a Type narrows the
Model list rather than offering every model in the department.

## Verification

`tools/server-checks.py`'s asset-form group: the Model widget is a combobox, its values are
the distinct models in the register, changing the Type narrows them, and a model typed that
is in no list is still saved.

## Not in this ticket

A `models` table. A model is a column on an asset, not an entity - nothing references one,
nothing is recorded against one, and a table would be a schema claiming otherwise.

## As built

Done as filed. Two things worth recording.

**The list is narrowed by the Asset Type and does not fall back when that type
has none.** The ticket says "falling back to every model when no type is
chosen", and that is what it does - no type picked offers every model in the
sheet. A type that is picked and has no model yet offers **nothing**, which is
the honest answer: offering every Screen model to somebody adding a UPS is the
noise this field exists to remove, and the widget is editable, so the first
model for a type is typed here. The caption says which of the three cases the
list is in.

**The list is re-read from a trace on the Asset Type variable**, not from
`<<ComboboxSelected>>`. That field is editable too, so a type typed in has to
reach this the same way a type picked from the list does.

## Verified

- `tools/server-checks.py` (121 groups), `tools/cascade-audit.py` (no drift) and
  `tools/client-checks.py` (12 groups) all exit 0.
- The new group opens the real Lookup Sheet window and the real Add Asset form.
  It is the **first** group to open either: both are named in `CLAUDE.md`'s list
  of dialogs measured against their own children and neither was reachable from
  the size group's openers, so both are measured here too - Lookup Sheet is
  resizable on both axes and reported rather than judged, Add Asset holds its
  children's 455x521 exactly.
