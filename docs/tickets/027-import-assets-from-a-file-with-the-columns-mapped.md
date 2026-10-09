# 027 - Import assets from xlsx or CSV, with the columns mapped by hand when they cannot be guessed

**Type:** feature · **Depends on:** 024, 025

## What changes

A second door into the register, beside the one-at-a-time form: **Import Assets**, reached
from the Lookup Sheet window, taking an `.xlsx` or a `.csv` and adding what it holds.

`POST /lookup/upload` is not that door and is not touched. It replaces the whole register
with a workbook in **this** application's own four-column shape. This one takes a file
written by somebody else - a vendor's delivery note, a finance export - whose columns are
named whatever they are named and whose rows are only sometimes valid.

Three stages, in this order, and **nothing is written until all three have passed**:

1. **Map.** Headers are matched against the four fields by name, case- and
   punctuation-insensitively (`Asset No.`, `asset_number`, `Serial`, `Model`, `Type`). Every
   mapping the guess made is shown for confirmation rather than applied silently, and any
   field it could not guess is an unfilled dropdown over the file's columns. An unmapped
   Asset Type, or both identifiers unmapped, cannot proceed - those are what rule 5's shape
   and rule 2 need. A column mapped to nothing is ignored.
2. **Validate.** Every row is checked as the form checks one: at least one identifier, an
   Asset Type present, no collision with the register and none with another row in the same
   file (025's rule, through 025's helper). The result is a table - row number, what it
   would become, and the refusal where there is one - so the operator sees the whole answer
   before committing rather than one refusal at a time.
3. **Commit.** The valid rows are written through `_save_asset` in one transaction. The
   refused rows are **not** written and not silently dropped: the operator chooses to
   commit the valid ones and is told how many were left, or to go back and fix the mapping.

A **new Asset Type** arriving in an import is confirmed once, listing the new types, for the
reason the asset form asks: it reaches every client's dropdown (rule 2).

Takes the **admin password**, at the Lookup Sheet window's own field, checked with
`_admin_password_ok` directly - the register is what makes rules 2 and 6 trustworthy, so it
is not a delegable capability (rule 11, ADR-0006).

## Where the code goes

The mapping and validation are a helper pair in `server.py` (`_map_import_columns`,
`_validate_import_rows`) rather than logic inside a Tk callback: **028 and 032 both call
them**, and a copy in each is what rule 10 exists to prevent. CSV is read with the stdlib
`csv` module and xlsx with the `openpyxl` already vendored - no new dependency.

## Verification

`tools/server-checks.py` gains a group against the two helpers, not the window: headers
guessed under punctuation and case, a header that cannot be guessed left unmapped rather
than mapped to the nearest thing, a file colliding with itself refused, a file colliding
with the register refused naming the register's row, and a commit writing exactly the valid
rows and nothing else.

## Not in this ticket

Who may import. This is the Admin at the console; the Storekeeper's path is 028 and 029.

## As built

Done as filed. The three stages are one dialog whose body is replaced rather
than three windows, so **Back to the columns** from the Validate stage is the
same mapping the operator just confirmed rather than a re-guess, and the four
helpers behind it are ordinary module functions - `_import_file_rows`,
`_map_import_columns`, `_validate_import_rows`, `_import_assets` - which is what
028 and 032 will call.

Four decisions the ticket left open:

- **The aliases are deliberately tight.** `asset_number` answers to
  `assetnumber`, `assetno`, `assetnum`, `assettag`, `assetid`, `assetcode` and
  `barcode`, and **not** to a bare `No` or `Number`: a column called `No` is a
  row number at least as often as an Asset Number, and the ticket asks for an
  unguessable header to be left unmapped. An operator filling in a blank is a
  better failure than one confirming a wrong guess, because the blank is
  visible and the guess reads as already decided.
- **A column is claimed by at most one field.** A file carrying both `Serial`
  and `SN` gives the first to Serial Number and leaves the second alone, rather
  than two fields reading one column; the dialog refuses that by hand too, for
  a mapping the operator makes.
- **The refusal for a collision inside the file is a different sentence** from
  the one for a collision with the register. The register's is
  `_IDENTIFIER_TAKEN`, worded once and shared with `_save_asset` - 025's
  sentence, naming the asset in the way. The file's names the **row number** in
  this file, because the remedy is in the spreadsheet rather than in the sheet.
- **`_import_assets` adds; it never replaces.** That is the whole difference
  between this door and `POST /lookup/upload`, and it is the half a careless
  second import would get wrong. One `lookup.imported` entry per import says
  how many were written and how many were refused.

The new Asset Type question is asked **once for the file**, listing every new
type, rather than once per row - the same question the asset form asks, asked
about a file. A model is still not asked about, for 026's reason.

## Verified

- `tools/server-checks.py` (122 groups), `tools/cascade-audit.py` (no drift) and
  `tools/client-checks.py` (12 groups) all exit 0.
- The real window, driven end to end with the file dialog stubbed: the footer
  carries Import Assets, a four-column CSV is guessed correctly and shown for
  confirmation, the Validate table answers all four rows - two added, one
  refused for colliding with the register by a mis-cased Asset Number, one for
  carrying no identifier - the new Asset Type is asked about once, the two valid
  assets are written, the Lookup Sheet window reloads showing three, and the
  line it is left with says 2 added and 2 refused and not written.
