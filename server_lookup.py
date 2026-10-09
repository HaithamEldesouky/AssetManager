"""
Asset Manager - the asset lookup's write path, and the proposals.

How an asset gets into the Assets register and how one is asked for: the
embedded sheet a first run writes and the workbook both directions of the
interchange format use (`_ensure_sample_lookup`, `_xlsx_asset_rows`,
`_lookup_xlsx_bytes`, `_seed_assets_if_empty`), the column mapping and the
row-by-row verdicts an import is decided by (`_import_key`,
`_map_import_columns`, `_check_import_mapping`, `_check_swapped_columns`,
`_import_file_rows`, `_validate_import_rows`, `_import_assets`,
`_replace_assets`), the proposals
a Client raises and the Admin answers (`_AssetRefused`, `_load_proposals`,
`_propose_asset`, `_propose_batch`, `_decide_proposal`, ADR-0017), and the
three readers every caller asks what the sheet currently says
(`_load_lookup_table`, `_asset_models`, `_lookup_asset_types`).

Lifted out of `server.py` by #229 unchanged - the last of the six clusters
046 (#220) named and left in it, behind `server_mail.py`, `server_sync.py`,
`server_clients.py`, `server_log.py` and `server_archive.py`. 769 lines, the
largest of the six, and one contiguous block only because 041 had already
taken the `assets` table's four functions out from around it.

**No route came with it.** There is no `@app.route` anywhere in the moved
block. The nine that reach this code - `/lookup`, `/asset_types`,
`/asset_models`, `/lookup/file`, `/lookup/upload`, `/assets/propose`,
`/assets/import/preview`, `/assets/proposals` and
`/assets/proposals/decide` - all stay in `server.py` and call in, which is
the shape #226 gave the `/clients*` routes, #227 gave `POST /clients/log`
and #228 gave `POST /records/import`. `@app`, `@door`, `DOOR_OPEN`,
`request` and `jsonify` are absent from this file entirely and
`docs/reference/api.md`'s rows for those nine are unchanged.

**This is a module beside the registers, not a second interface onto
them.** 046 said to grep every call from this block into `register_assets`
and `register_transactions` before writing `bind()`, because that count is
what decides which of the two it is. The answer is three names into
`register_assets` - `_load_assets`, `_save_asset` and the refusal
`_IDENTIFIER_TAKEN` they raise - and **none at all** into
`register_transactions`. Three reads and no writes of its own: every asset
this file lands goes through `_save_asset`, the one writer, exactly as it
did when both sat in `server.py`. So the three are imported from
`register_assets` directly rather than handed over, which is what
`register_transactions.py` does for `_asset_key_sql` and for its reason -
asking the register rather than wording its rule twice.

`DEFAULT_LOOKUP_B64` did **not** move (rule 11): the workbook is embedded in
`server.py` and the two doors that update it are there. It comes over
through `bind()` as the bytes `_ensure_sample_lookup` writes on a first run.
Rule 2 is unchanged too - `GET /asset_types` still serves the distinct
`asset_type` values of the `assets` table, `_lookup_asset_types` here being
what it calls and `ASSET_TYPES` the bound fallback for a sheet that defines
none.

**Five of the names defined here are handed to two other modules.**
`register_transactions.bind()` takes `_load_lookup_table` and
`server_sync.bind()` takes `_check_import_mapping`, `_map_import_columns`,
`_IMPORT_FIELDS` and `_IMPORT_LABELS`. Both calls sit far below
`server.py`'s flat import of this module, so each is handed this file's
object and there is one copy of each rule in the process - the same thing
#227's flat import of `_log_event` bought the five calls above it.

Headless-safe: nothing here draws, so `server.py` imports it at module
level. The two windows that drive it, `server_gui.py`'s Manage Assets and
Asset Proposals, reach it as `S.<name>` and the Tk stays there, which is
what lets `tools/server-checks.py` call every refusal directly.

`server.py` runs as `__main__` under `applaunch`'s `runpy.run_path`, so
`from server import get_db` would execute the whole server a second time
rather than reach the one running - the reason `server_cert.py` set this
pattern and every module since has repeated it.
"""

import base64
import io
import os
import sqlite3
from datetime import datetime

# The Assets register, asked rather than re-worded: `_save_asset` is the one
# writer every asset this file lands goes through, `_load_assets` the reader
# an import is validated against, and `_IDENTIFIER_TAKEN` the sentence that
# writer refuses with - and `_asset_shape_error` the shape it holds an asset
# to, which a proposal and an import's verdicts ask before anything is written
# (103). Imported directly rather than bound, which is what
# `register_transactions.py` does for `_asset_key_sql` and for its reason.
# `register_assets` imports nothing of ours, so there is no cycle.
from register_assets import (_IDENTIFIER_TAKEN, _asset_shape_error,
                             _load_assets, _save_asset)

# Handed over by server.py's bind() below, before anything here is called.
# Named exactly as server.py names them, so the code moved in reads there
# and here as one thing.
ASSET_TYPES = None
DEFAULT_LOOKUP_B64 = None
LOOKUP_PATH = None
_log_event = None
get_db = None


def bind(*, asset_types, default_lookup_b64, lookup_path, get_db, log_event):
    """Give this module everything it reads out of server.py. Called once.

    Keyword-only and exhaustive, the same contract `server_cert.bind()`, the
    three registers', `server_mail.bind()`'s, `server_sync.bind()`'s,
    `server_clients.bind()`'s, `server_log.bind()`'s and
    `server_archive.bind()`'s carry: every name the moved code reads out of
    `server.py` is on this list, built with a `symtable` sweep over the
    moved block rather than by hand, because 036's own note found fourteen
    names a hand-written list had missed. Thirteen free names came back,
    five of them stdlib this module imports itself (`base64`, `datetime`,
    `io`, `os`, `sqlite3`) and three `register_assets`' own, imported from
    there above.

    **Five rather than the longest list of the six**, which is not what 046
    expected. The coupling it warned about is real and it runs the other
    way: this file reaches into `register_assets` three times and that is an
    import, not a hand-over. Nothing here is re-pointed by
    `tools/server-checks.py` between check groups, so none of the five is a
    callable the way `server_sync.py`'s, `server_log.py`'s and
    `server_archive.py`'s `db_path` is.

    `default_lookup_b64` is the embedded workbook of rule 11, which stays in
    `server.py` with the two doors that update it; it arrives here as the
    bytes a first run writes and nothing in this file rewrites it.

    Called from `server.py`'s bind block. Nothing orders it against the
    other calls - what two of them are handed out of this file are function
    objects off the flat import at the top, not anything `bind()` sets.

    What is bound here is module state, so a process holding **two** server
    modules leaves this one pointing at whichever imported it last. A real
    install has one; `tools/server-checks.py` is the only thing that imports
    a second, and it gives each staged copy a `server_lookup` of its own.
    """
    global ASSET_TYPES, DEFAULT_LOOKUP_B64, LOOKUP_PATH, _log_event
    ASSET_TYPES = asset_types
    DEFAULT_LOOKUP_B64 = default_lookup_b64
    LOOKUP_PATH = lookup_path
    _log_event = log_event
    # `global get_db` is a syntax error where `get_db` is also the
    # parameter, and the moved code calls it bare - so the module global is
    # set the one way left, exactly as the three modules before this did.
    globals()["get_db"] = get_db


# ─── Lookup helpers ───────────────────────────────────────────────────────────

def _ensure_sample_lookup():
    """Write the embedded real asset_lookup.xlsx if no file exists yet.

    Still here after 024, and still the first thing a first run does: the sheet
    is what `_seed_assets_if_empty` reads the assets in from, so this is how a
    brand-new install gets a Lookup Sheet at all. It is not kept in step with
    the table afterwards - see ADR-0011.
    """
    if os.path.exists(LOOKUP_PATH):
        return
    try:
        raw = base64.b64decode(DEFAULT_LOOKUP_B64)
        with open(LOOKUP_PATH, 'wb') as f:
            f.write(raw)
    except Exception:
        pass  # fallback: leave missing, server will still run


def _xlsx_asset_rows(src):
    """The four columns of a workbook: number, serial, type, model.

    The one reader of the interchange format, used by both doors it comes in
    through: the seed that fills an empty table from the sheet beside the
    server, which hands it a path, and POST /lookup/upload, which hands it the
    uploaded bytes - openpyxl takes either, so an upload needs no file on
    disk. Only a row with nothing in its three first columns is dropped here:
    what a row must carry to be an asset is `_asset_shape_error`'s to say, and
    an upload refuses with every row that fails it rather than losing them
    (103). The seed keeps its own leniency - see `_seed_assets_if_empty`.
    """
    import openpyxl
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()
    out = []
    for row in rows:
        if not row or len(row) < 3:
            continue
        an = str(row[0]).strip() if row[0] else ""
        sn = str(row[1]).strip() if row[1] else ""
        at = str(row[2]).strip() if row[2] else ""
        am = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        if am.upper() in ("N/A", "N\\A", "NA", "N.A", "-"):
            am = ""
        if not (an or sn or at):
            continue
        out.append((an, sn, at, am))
    return out


def _lookup_xlsx_bytes(rows):
    """The Lookup Sheet as an xlsx, in the four columns it has always had.

    The other half of `_xlsx_asset_rows`, and the reason the workbook is still
    a format worth keeping: this is what GET /lookup/file serves and what
    somebody edits before uploading it back. It writes to bytes rather than to
    a path - since 024 there is no file on disk for it to be the current copy
    of, and a download is the only caller.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Asset Lookup"
    blue_fill = PatternFill("solid", fgColor="0078D4")
    hdr_font  = Font(bold=True, color="FFFFFF", name="Segoe UI", size=10)
    headers   = ["Asset Number", "Serial Number", "Asset Type", "Asset Model"]
    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font      = hdr_font
        cell.fill      = blue_fill
        cell.alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 26
    for ri, row_data in enumerate(rows, 2):
        for ci in range(4):
            ws.cell(row=ri, column=ci + 1,
                    value=row_data[ci] if len(row_data) > ci else "")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _seed_assets_if_empty(c):
    """Fill an empty `assets` table from asset_lookup.xlsx. Returns how many.

    Runs on a cursor the caller owns and commits, because that caller is
    `init_db()` and this is part of making a database. It is the first-run path
    and the migration's fallback at once: a brand-new install has no sheet but
    the one embedded in this exe, which `_ensure_sample_lookup` writes out; an
    existing install is seeded by migration 009 from the sheet beside its
    database, and where that found none - a `db_path` that moved the database
    away from the server - this finds the one beside the server.

    A sheet that cannot be read leaves the table empty rather than stopping the
    server: an empty Lookup Sheet refuses every Transaction (rule 6), which is
    visible immediately and is fixed by uploading a sheet, while a server that
    will not start is neither. **Nor does a sheet that contradicts itself**: an
    identifier a row further up already used is cleared from this one, by the
    rule `_resolve_asset_identity` applies to the table - the asset is kept and
    still carries its other identifier, and what was cleared is returned for
    the caller to log. The real shipped sheet needs it: 6 of its 3462 rows
    share a Serial Number with another row. A row left with neither identifier
    is dropped, being a duplicate of an earlier row in both.

    Returns (how many rows were written, what was cleared).
    """
    if c.execute("SELECT COUNT(*) FROM assets").fetchone()[0]:
        return 0, []
    _ensure_sample_lookup()
    if not os.path.exists(LOOKUP_PATH):
        return 0, []
    try:
        rows = _xlsx_asset_rows(LOOKUP_PATH)
    except Exception:
        return 0, []
    now = datetime.now().isoformat()
    seen = {"asset_number": {}, "serial_number": {}}
    cleared, keep = {}, []
    for an, sn, at, am in rows:
        # A row with no Asset Type is skipped, as the reader skipped it before
        # 103 moved the refusal to the upload: a first run has nobody to show
        # a refusal to, and an empty Lookup Sheet is fixed by an upload.
        if not at:
            continue
        vals = {"asset_number": an, "serial_number": sn}
        for col in ("asset_number", "serial_number"):
            v = vals[col]
            if not v:
                continue
            if v.lower() in seen[col]:
                cleared[(col, seen[col][v.lower()])] = (
                    cleared.get((col, seen[col][v.lower()]), 0) + 1)
                vals[col] = ""
            else:
                seen[col][v.lower()] = v
        if vals["asset_number"] or vals["serial_number"]:
            keep.append((vals["asset_number"], vals["serial_number"], at, am,
                         now))
    c.executemany(
        "INSERT INTO assets(asset_number, serial_number, asset_type,"
        " asset_model, created_at, created_by)"
        " VALUES (?, ?, ?, ?, ?, 'asset_lookup.xlsx')", keep)
    return len(keep), [(col, v, n) for (col, v), n in cleared.items()]


# The four fields, and the header spellings each is recognised by - compared
# with everything but letters and digits stripped, so `Asset No.`, `asset_no`
# and `ASSET NO` are one spelling. Deliberately tight: a column called `No` is
# a row number at least as often as an Asset Number, and the ticket behind this
# asks for an unguessable header to be left **unmapped** rather than mapped to
# the nearest thing - an operator confirming a wrong guess is worse than one
# filling in a blank.
_IMPORT_FIELDS = ("asset_number", "serial_number", "asset_type", "asset_model")

_IMPORT_LABELS = {"asset_number": "Asset Number",
                  "serial_number": "Serial Number",
                  "asset_type":    "Asset Type",
                  "asset_model":   "Asset Model"}

_IMPORT_ALIASES = {
    "asset_number":  ("assetnumber", "assetno", "assetnum", "assettag",
                      "assetid", "assetcode", "barcode"),
    "serial_number": ("serialnumber", "serialno", "serialnum", "serial", "sn"),
    "asset_type":    ("assettype", "equipmenttype", "devicetype", "type",
                      "category"),
    "asset_model":   ("assetmodel", "modelname", "model"),
}


def _import_key(text):
    """A header reduced to what is worth comparing: letters and digits only."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _map_import_columns(headers):
    """Guess which column is which field. Returns {field: index or None}.

    The guess is a **proposal**, not a decision: every caller shows it for
    confirmation, because a wrong guess applied silently writes the serial
    numbers into the Asset Number column of three hundred assets and the first
    anybody hears of it is a scan that finds nothing.

    A column is claimed by at most one field, and a field that matches nothing
    stays None rather than taking the nearest header. The aliases are ordered
    most specific first within each field, so a file carrying both `Asset No`
    and `No` gives the first to `asset_number` and leaves the second alone.
    """
    keys  = [_import_key(h) for h in headers]
    taken = set()
    out   = dict((f, None) for f in _IMPORT_FIELDS)
    for field in _IMPORT_FIELDS:
        for alias in _IMPORT_ALIASES[field]:
            hit = [i for i, k in enumerate(keys)
                   if k == alias and i not in taken]
            if hit:
                out[field] = hit[0]
                taken.add(hit[0])
                break
    return out


def _check_import_mapping(mapping):
    """Why this mapping cannot be used, or "" where it can.

    Worded once because two importers read it: the Server GUI's Import Assets,
    where the Admin confirms the guess in front of the sheet, and the
    Storekeeper's, which posts its confirmed mapping here because a client does
    not import this file (rule 10). Two copies would drift into a mapping one
    importer accepts and the other refuses, which is the same file arriving at
    two doors and being called two different things.
    """
    used = [c for c in mapping.values() if c is not None]
    if len(used) != len(set(used)):
        return ("Two fields are pointed at one column. Each column describes "
                "one thing.")
    if mapping.get("asset_type") is None:
        return ("An asset needs an Asset Type - it is what GET /asset_types "
                "serves to every client (rule 2), and no import may invent "
                "one.")
    if (mapping.get("asset_number") is None
            and mapping.get("serial_number") is None):
        return ("An asset needs an Asset Number or a Serial Number (rule 5). "
                "With neither column mapped, this file describes no asset this "
                "server could ever look up.")
    return ""


def _check_swapped_columns(rows, mapping, assets=None):
    """A WARNING, not a refusal: "" where the mapping is not suspect.

    `_check_import_mapping` can only see the header - it has no way to tell
    an Asset Number column from a Serial Number column beside it, because
    both are free text and either could hold either. This looks at what the
    two mapped columns actually contain: if more of the Asset Number
    column's values are Serial Numbers already in the register than are
    Asset Numbers, and more of the Serial Number column's are Asset Numbers
    than Serial Numbers, the two are very likely swapped. It is a warning
    and not `_check_import_mapping`'s refusal because a register with
    nothing in it yet, or a file of assets nobody has seen before, matches
    neither column against anything - the absence of a match is not evidence
    of a swap, only silence.
    """
    a_i, s_i = mapping.get("asset_number"), mapping.get("serial_number")
    if a_i is None or s_i is None or not rows:
        return ""
    if assets is None:
        assets = _load_assets()
    known_numbers = {a["asset_number"].lower() for a in assets if a["asset_number"]}
    known_serials = {a["serial_number"].lower() for a in assets if a["serial_number"]}

    def _hits(col):
        vals = [r[col].strip().lower() for r in rows if col < len(r) and r[col]]
        return (sum(1 for v in vals if v in known_numbers),
                sum(1 for v in vals if v in known_serials))

    number_col_as_number, number_col_as_serial = _hits(a_i)
    serial_col_as_number, serial_col_as_serial = _hits(s_i)
    if (number_col_as_serial > number_col_as_number
            and serial_col_as_number > serial_col_as_serial):
        return ("The Asset Number and Serial Number columns look swapped: "
                "%d value(s) in the mapped Asset Number column match an "
                "existing Serial Number against %d that match an Asset "
                "Number, and %d value(s) in the mapped Serial Number column "
                "match an existing Asset Number against %d that match a "
                "Serial Number. Check the mapping before importing."
                % (number_col_as_serial, number_col_as_number,
                   serial_col_as_number, serial_col_as_serial))
    return ""


def _import_file_rows(path):
    """(headers, rows) out of an .xlsx or a .csv. Every cell a stripped string.

    The two formats are read by the two readers already here - `openpyxl`,
    which the Lookup Sheet's own workbook goes through, and the stdlib `csv` -
    so this adds no dependency to a vendored `lib` pinned to one Python minor
    version (rule 13). The file is somebody else's: a vendor's delivery note, a
    finance export. Nothing about its shape is assumed beyond a header row.
    """
    if path.lower().endswith(".csv"):
        import csv
        with io.open(path, encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.reader(f)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    rows = [[("" if c is None else str(c)).strip() for c in r] for r in rows]
    while rows and not any(c for c in rows[0]):
        rows.pop(0)
    if not rows:
        return [], []
    return rows[0], [r for r in rows[1:] if any(c for c in r)]


def _validate_import_rows(rows, mapping, assets=None, pending=None):
    """What each row would become, and why it cannot. Never writes anything.

    Returns a list of dicts: the four fields, the `line` the row sat on in the
    file counting the header as 1, and `error` - empty where the row is good.
    The whole file is answered at once on purpose: an operator fixing a
    spreadsheet wants the list of what is wrong with it, not the first refusal
    and then another run.

    Every rule is the one `_save_asset` holds a single asset to, because that is
    the function these rows are about to go through: `_asset_shape_error`'s
    shape (103), and an identifier that names one asset
    (025) - checked against the Lookup Sheet **and** against the rows above it
    in this same file, since two rows of one import collide exactly as a row and
    the table do. The refusal is worded once, in `_IDENTIFIER_TAKEN`.

    `assets` is the Lookup Sheet to check against, defaulting to what is there;
    a caller that has already read it passes it rather than reading it again.
    `pending` is the proposals waiting for the Admin, and is the one thing here
    that is optional rather than defaulted: a file on its way to becoming
    **proposals** (029) collides with one already waiting exactly as it does
    with the register, while the Admin's own importer writes the register
    directly and a proposal is not in its way. The refusal is `_propose_asset`'s
    own sentence, so a file and a single asset are told the same thing.
    """
    if assets is None:
        assets = _load_assets()
    # An Asset Type that matches one the sheet already has apart from case IS
    # that type, so the row becomes it. Both importers ask before adding a type
    # nobody has bought before, because it reaches every client's dropdown
    # (rule 2) - and both asked that question against a case-folded comparison
    # while writing the case they were handed, so a delivery note in upper case
    # added LAPTOP beside Laptop with nothing asked, which is precisely the
    # case the question exists for. It is folded here rather than in
    # `_save_asset` because the one writer is also what POST /lookup/upload
    # goes through, and that door replaces the sheet - folding a type onto the
    # spelling of a row that is about to be deleted answers the wrong question.
    # Here it is also what the operator is shown: this function says what each
    # row would become, and an Asset Type column showing a spelling that will
    # not be written is the same lie in a different place. First occurrence
    # wins, `_load_assets` being ordered by id, so a sheet that already holds
    # two spellings folds onto the older of them rather than onto whichever
    # sorted first.
    canon = {}
    for a in assets:
        if a["asset_type"]:
            canon.setdefault(a["asset_type"].lower(), a["asset_type"])
    taken = {}
    for a in assets:
        for col in ("asset_number", "serial_number"):
            if a[col]:
                taken[(col, a[col].lower())] = (
                    a["asset_number"] or a["serial_number"],
                    a["asset_type"] or "no type", None)
    # The register first, so an identifier that is in both is answered with
    # "that asset exists and can be transacted now" rather than with "somebody
    # has asked about it" - the first is what the reader actually wanted.
    for p in (pending or ()):
        for col in ("asset_number", "serial_number"):
            if p[col]:
                taken.setdefault((col, p[col].lower()), (
                    p["asset_number"] or p["serial_number"],
                    p["asset_type"] or "no type",
                    (p["id"], p["proposed_by"])))
    out = []
    for n, row in enumerate(rows, 2):

        def cell(field):
            i = mapping.get(field)
            return (row[i].strip()
                    if i is not None and i < len(row) and row[i] else "")

        got = dict((f, cell(f)) for f in _IMPORT_FIELDS)
        got["asset_type"] = canon.get(got["asset_type"].lower(),
                                      got["asset_type"])
        got["line"] = n
        got["error"] = _asset_shape_error(got["asset_number"],
                                          got["serial_number"],
                                          got["asset_type"])
        if not got["error"]:
            for col in ("asset_number", "serial_number"):
                value = got[col]
                if not value:
                    continue
                held = taken.get((col, value.lower()))
                if held is None:
                    continue
                if held[2] is None:
                    got["error"] = _IDENTIFIER_TAKEN % (
                        _IMPORT_LABELS[col], value, held[0], held[1])
                elif isinstance(held[2], tuple):
                    got["error"] = _PROPOSAL_PENDING % (
                        _IMPORT_LABELS[col], value, held[2][0], held[2][1])
                else:
                    got["error"] = (
                        "%s %s is on row %d of this file as well. One of the "
                        "two rows describes an asset this file does not hold, "
                        "and which is not something an import gets to decide."
                        % (_IMPORT_LABELS[col], value, held[2]))
                break
        if not got["error"]:
            for col in ("asset_number", "serial_number"):
                if got[col]:
                    taken[(col, got[col].lower())] = (
                        got["asset_number"] or got["serial_number"],
                        got["asset_type"], n)
        out.append(got)
    return out


def _import_assets(verdicts, actor="Admin (Server GUI)", address=""):
    """Write the rows that passed, in one transaction. Returns how many.

    The refused rows are not written and not quietly dropped - the caller has
    already shown the operator every one of them and asked. This adds to the
    Lookup Sheet rather than replacing it, which is the whole difference between
    this door and `POST /lookup/upload`: that one takes a workbook in this
    application's own shape and means "this is the Lookup Sheet now", while a
    file somebody else wrote means "these assets exist as well".
    """
    good = [v for v in verdicts if not v["error"]]
    conn = get_db()
    try:
        for v in good:
            _save_asset(v["asset_number"], v["serial_number"], v["asset_type"],
                        v["asset_model"], actor=actor, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _log_event("lookup.imported",
               "%d asset(s) added from an imported file, %d row(s) refused"
               % (len(good), len(verdicts) - len(good)),
               actor=actor, level="warn", address=address)
    return len(good)


class _AssetRefused(ValueError):
    """A refusal carrying the `code` the wire answers with.

    The windows show `str(...)`, which is the sentence, and the endpoint adds
    the code beside it - so a Storekeeper can tell "that asset already exists"
    from "somebody else has already proposed it" without parsing English, and
    both doors say the same words either way. It is a `ValueError` because
    every writer here already refuses with one and `write()` in the Lookup
    Sheet window shows those as they are.

    A **batch** refusal carries `refusals` beside the code - one entry per row
    that cannot be recorded, naming the line it sat on in the file. A batch is
    all or nothing (029), so what the caller needs is the list to correct
    rather than the first thing that was wrong with it.
    """

    def __init__(self, message, code="", refusals=()):
        ValueError.__init__(self, message)
        self.code = code
        self.refusals = list(refusals)


_PROPOSAL_PENDING = ("%s %s is already waiting for the Admin - proposal #%d, "
                     "from %s. It is the same asset, so one answer covers "
                     "both.")

PROPOSAL_STATUSES = ("pending", "approved", "rejected")


def _load_proposals(status=""):
    """The proposals, newest first, as dicts. `status` narrows to one state."""
    conn = get_db()
    try:
        sql  = ("SELECT id, asset_number, serial_number, asset_type,"
                " asset_model, proposed_by, proposed_at, client_id, status,"
                " decided_at, decided_by, reason FROM asset_proposals")
        args = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _propose_asset(asset_number, serial_number, asset_type, asset_model="",
                   proposed_by="", client_id="", address="", conn=None,
                   proposed_at="", log=True):
    """The one writer of a proposal. Returns its id.

    A proposal is an asset the Storekeeper is holding and the Admin has not
    approved. It changes nothing until one does, which is what makes it safe to
    accept from an unauthenticated client (ADR-0002's reason, ADR-0012's
    argument) - rule 6 is only worth anything while the register is trusted,
    and the register is trusted because one credential changes it.

    Refused for the shape an asset must have - `_asset_shape_error`'s, the one
    `_save_asset` will hold it to on approval (103) - and for two kinds of
    duplicate, each with
    its own sentence because each has a different remedy: an identifier the
    **register** already holds means the asset exists and can be transacted
    now, which is the answer the Storekeeper actually wanted; one a **pending
    proposal** holds means somebody has already asked and the answer is coming.
    A **rejected** proposal blocks nothing - the hardware may have turned up
    after all, and re-proposing it is how that is said.

    The last three arguments are what makes a delivery one batch rather than
    twenty (029), and they are `_save_asset`'s own shape: a caller holding the
    transaction passes its `conn` and commits, one `proposed_at` stamps every
    row of a batch so the Server GUI can group them, and `log=False` leaves the
    entry to that caller - a `_log_event` opens a connection of its own, which
    against an uncommitted write transaction is exactly the contention
    `_log_event` refuses to wait for.
    """
    asset_number  = (asset_number or "").strip()
    serial_number = (serial_number or "").strip()
    asset_type    = (asset_type or "").strip()
    asset_model   = (asset_model or "").strip()
    proposed_by   = (proposed_by or "").strip() or "Storekeeper"
    refused = _asset_shape_error(asset_number, serial_number, asset_type)
    if refused:
        raise _AssetRefused(refused, "bad_asset")
    own  = conn is None
    conn = get_db() if own else conn
    now  = (proposed_at or "").strip() or datetime.now().isoformat()
    try:
        for value, col, what in ((asset_number, "asset_number", "Asset Number"),
                                 (serial_number, "serial_number",
                                  "Serial Number")):
            if not value:
                continue
            held = conn.execute(
                "SELECT asset_number, serial_number, asset_type FROM assets"
                " WHERE %s = ? COLLATE NOCASE" % col, (value,)).fetchone()
            if held:
                raise _AssetRefused(
                    _IDENTIFIER_TAKEN % (
                        what, value,
                        held["asset_number"] or held["serial_number"],
                        held["asset_type"] or "no type"),
                    "duplicate_identifier")
            waiting = conn.execute(
                "SELECT id, proposed_by FROM asset_proposals WHERE %s = ?"
                " COLLATE NOCASE AND status = 'pending'" % col,
                (value,)).fetchone()
            if waiting:
                raise _AssetRefused(
                    _PROPOSAL_PENDING % (what, value, waiting["id"],
                                         waiting["proposed_by"]),
                    "already_proposed")
        cur = conn.execute(
            "INSERT INTO asset_proposals(asset_number, serial_number,"
            " asset_type, asset_model, proposed_by, proposed_at, client_id,"
            " status) VALUES (?,?,?,?,?,?,?,'pending')",
            (asset_number, serial_number, asset_type, asset_model, proposed_by,
             now, (client_id or "")[:120]))
        if own:
            conn.commit()
        pid = cur.lastrowid
    finally:
        if own:
            conn.close()
    if log:
        _log_event("asset.proposed",
                   "%s proposed as %s%s, waiting for the Admin (proposal #%d)"
                   % (asset_number or serial_number, asset_type,
                      " %s" % asset_model if asset_model else "", pid),
                   actor=proposed_by, client_id=client_id, address=address,
                   level="warn")
    return pid


# A delivery is twenty machines on a vendor's spreadsheet, and this is what one
# batch may carry. Bounded for the reason `_LOG_BATCH_MAX` is - the endpoint is
# unauthenticated (ADR-0012), and an age bound alone cannot bound a table
# anybody on the network may write to. An over-long file is refused **with the
# count** rather than half accepted: half a delivery recorded is worse than
# none, because nothing says which half.
_PROPOSAL_BATCH_MAX = 200

# And how many columns of somebody else's spreadsheet are worth looking at. A
# header row is a list a caller on the network chooses the length of, and four
# of its columns are all this ever maps.
_IMPORT_COLUMNS_MAX = 200


def _propose_batch(rows, proposed_by="", client_id="", address="", source=""):
    """A file's worth of proposals, written as one batch. Returns (ids, stamp).

    **All or nothing.** Every row is put through `_validate_import_rows` - the
    same helper 027's importer shows the Admin, so the rules a file is held to
    are one fact and not two (029) - and a single refusal refuses the file,
    carrying every line that is wrong with it. A delivery half recorded is
    worse than one refused: the rows that went in are indistinguishable from
    rows somebody typed, and the operator has no way to tell what to send
    again.

    That is also the honest answer to a file that collides **with itself**.
    Written row by row, the first row would be taken and the second refused
    with "somebody has already proposed this" - which is true, and the somebody
    was this same file one line earlier.

    Every row of one batch carries one `proposed_at`, which is what the Server
    GUI groups on: approving a delivery is one decision rather than twenty.
    """
    rows = list(rows or ())
    if not rows:
        raise _AssetRefused("There is nothing in this file to propose.",
                            "no_rows")
    if len(rows) > _PROPOSAL_BATCH_MAX:
        raise _AssetRefused(
            "This file carries %d assets and one batch may carry %d. Nothing "
            "was recorded - split it and send it in parts, so what arrived and "
            "what did not is a question with an answer."
            % (len(rows), _PROPOSAL_BATCH_MAX), "too_many")
    mapping = dict((f, i) for i, f in enumerate(_IMPORT_FIELDS))
    grid = [[str((r or {}).get(f) or "").strip() for f in _IMPORT_FIELDS]
            for r in rows]
    verdicts = _validate_import_rows(grid, mapping, _load_assets(),
                                     _load_proposals("pending"))
    refused = [v for v in verdicts if v["error"]]
    if refused:
        raise _AssetRefused(
            "%d of %d row%s in this file cannot be proposed, so none of it "
            "was recorded." % (len(refused), len(verdicts),
                               "" if len(verdicts) == 1 else "s"),
            "bad_rows",
            [{"line": v["line"], "error": v["error"]} for v in refused])
    stamp = datetime.now().isoformat()
    conn  = get_db()
    ids   = []
    try:
        for v in verdicts:
            ids.append(_propose_asset(
                v["asset_number"], v["serial_number"], v["asset_type"],
                v["asset_model"], proposed_by=proposed_by,
                client_id=client_id, address=address, conn=conn,
                proposed_at=stamp, log=False))
        conn.commit()
    finally:
        conn.close()
    _log_event("asset.proposals_imported",
               "%d asset(s) proposed as one batch from %s, waiting for the "
               "Admin (proposals #%d-#%d)"
               % (len(ids), source or "a file", ids[0], ids[-1]),
               actor=proposed_by or "Storekeeper", client_id=client_id,
               address=address, level="warn")
    return ids, stamp


def _decide_proposal(proposal_id, approve, decided_by="Admin (Server GUI)",
                     reason=""):
    """Approve a proposal into the register, or reject it. Returns its row.

    Approving writes through `_save_asset`, the one writer, so a proposal and a
    hand-typed asset cannot mean different things - and it is checked there
    rather than here, so a register that gained that identifier while the
    proposal waited refuses **and leaves the row pending**, which is the state
    it is actually in.

    A rejection **keeps the row** and the reason on it, the way ADR-0003 keeps
    a cancelled Transaction: the Storekeeper is owed the answer, and "this
    serial was refused last month" is the record that stops it being proposed
    weekly. There is deliberately no delete.
    """
    reason = (reason or "").strip()
    if not approve and not reason:
        raise _AssetRefused("A rejection needs a reason - it is the whole of "
                            "what the Storekeeper is told.", "no_reason")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM asset_proposals WHERE id = ?",
            (proposal_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _AssetRefused("Proposal #%s is not there." % proposal_id,
                            "no_proposal")
    if row["status"] != "pending":
        raise _AssetRefused(
            "Proposal #%d was already %s%s." % (
                row["id"], row["status"],
                " by %s" % row["decided_by"] if row["decided_by"] else ""),
            "already_decided")
    if approve:
        _save_asset(row["asset_number"], row["serial_number"],
                    row["asset_type"], row["asset_model"], actor=decided_by)
    conn = get_db()
    try:
        conn.execute("UPDATE asset_proposals SET status=?, decided_at=?,"
                     " decided_by=?, reason=? WHERE id=?",
                     ("approved" if approve else "rejected",
                      datetime.now().isoformat(), decided_by, reason,
                      row["id"]))
        conn.commit()
    finally:
        conn.close()
    ident = row["asset_number"] or row["serial_number"]
    if approve:
        _log_event("asset.proposal_approved",
                   "proposal #%d approved - %s is in the Lookup Sheet as %s"
                   % (row["id"], ident, row["asset_type"]),
                   actor=decided_by, level="warn")
    else:
        _log_event("asset.proposal_rejected",
                   "proposal #%d rejected - %s (%s): %s"
                   % (row["id"], ident, row["proposed_by"], reason),
                   actor=decided_by, level="warn")
    return dict(row)


def _replace_assets(rows, actor="Admin", address=""):
    """Replace the whole Lookup Sheet, which is what an uploaded sheet means.

    One transaction, so a failure part way through leaves the Lookup Sheet
    as it was rather than half replaced - where the old code wrote a new
    workbook over the old one, and the same failure left a truncated file
    and nothing to go back to. **All or nothing** is what makes a refusal
    something to act on: a sheet that was half taken is neither the sheet
    that was uploaded nor the one that was there.

    Each row goes through `_save_asset`, so two rows of the uploaded sheet
    claiming one identifier are refused here exactly as two rows already in
    the table would be - the check is against what this transaction has
    written so far, which is the sheet itself. The `ValueError` is re-raised
    naming where in the sheet it was found, since the sentence `_save_asset`
    writes describes the asset in the way and not the row that met it.

    The shape is asked of **every** row first, before anything is deleted, and
    refused with the whole list in `refusals` (103): a sheet with forty rows
    missing a serial is one correction to the file, not forty uploads each
    naming the next.
    """
    refusals = []
    for n, (an, sn, at, am) in enumerate(rows, 1):
        refused = _asset_shape_error((an or "").strip(), (sn or "").strip(),
                                     (at or "").strip())
        if refused:
            refusals.append({"line": n, "error": "Asset %d (%s): %s" % (
                n, an or sn or "no identifier", refused)})
    if refusals:
        raise _AssetRefused(
            "%d of %d asset%s in the uploaded sheet cannot be kept, so the "
            "Lookup Sheet was not replaced." % (len(refusals), len(rows),
                                                "" if len(rows) == 1 else "s"),
            "bad_rows", refusals)
    conn = get_db()
    try:
        conn.execute("DELETE FROM assets")
        for n, (an, sn, at, am) in enumerate(rows, 1):
            try:
                _save_asset(an, sn, at, am, actor=actor, conn=conn)
            except ValueError as e:
                conn.rollback()
                raise ValueError("Asset %d of %d in the uploaded sheet (%s): %s"
                                 % (n, len(rows), an or sn or "no identifier",
                                    e))
        conn.commit()
    finally:
        conn.close()
    # The Lookup Sheet is what makes rule 2's asset types and rule 6's refusal
    # trustworthy, so replacing it wholesale is worth a line of its own.
    _log_event("lookup.replaced", "%d asset(s)" % len(rows), actor=actor,
               level="warn", address=address)
    return len(rows)


def _load_lookup_table():
    """
    The Lookup Sheet keyed by both identifiers, both lowercased.
    Returns dict: lower(value) -> {"asset_type": ..., "asset_number": ...,
                                   "serial_number": ..., "asset_model": ...}

    Its signature and its return shape are what 024 deliberately did not move:
    rule 6, GET /asset_types, GET /lookup and the Server GUI's Add Transaction
    all read it, and that ticket moved the store without moving one rule. Only
    the body changed - a SELECT where it used to open a workbook on every call,
    for every Transaction submitted and every keystroke in a lookup field.
    """
    table = {}
    for a in _load_assets():
        entry = {"asset_type": a["asset_type"],
                 "asset_number": a["asset_number"],
                 "serial_number": a["serial_number"],
                 "asset_model": a["asset_model"]}
        if a["asset_number"]:
            table[a["asset_number"].lower()] = entry
        if a["serial_number"]:
            table[a["serial_number"].lower()] = entry
    return table


def _asset_models(for_type=""):
    """The Asset Models the register holds, for one type or for all of them.

    One spelling of a question asked from two places: the Lookup Sheet
    window's Asset Model combobox (026) and `GET /asset_models`. Narrowed by
    an Asset Type because the department's whole model list is noise in front
    of somebody adding a Screen; a type this register has no model for answers
    **nothing** rather than everything, which is the honest answer and the one
    that window already gave - the field is editable and that window is where
    the first one is typed.

    Read off the `assets` table rather than the workbook, which has been the
    interchange format since 024 and goes stale on purpose, and `_load_assets`
    caches nothing, so the answer is current the moment a row lands. An empty
    model is not a model - `''` is what the sheet says where it is N/A - so it
    is never served. The type is matched without regard to case for 027's
    reason: a sheet holding `Laptop` answers `LAPTOP` too.
    """
    rows = _load_assets()
    if for_type:
        return sorted({r["asset_model"] for r in rows
                       if r["asset_model"]
                       and r["asset_type"].lower() == for_type.lower()})
    return sorted({r["asset_model"] for r in rows if r["asset_model"]})


def _lookup_asset_types():
    """Distinct asset types present in the current lookup sheet, sorted.
    Falls back to the baked-in ASSET_TYPES when the sheet defines none — so the
    valid-type list is dynamic (driven by asset_lookup.xlsx) but never empty."""
    table = _load_lookup_table()
    types = sorted({e["asset_type"] for e in table.values() if e.get("asset_type")})
    return types or list(ASSET_TYPES)
