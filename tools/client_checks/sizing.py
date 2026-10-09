r"""The two source-only groups: no window takes its size from a branch, and
one `fit`, in the kit.

One of the check groups #238 split tools/client-checks.py into. The entry
point imports this module and runs every check_* function in it; what they
read - the staged apps, the sources, ok()/bad()/eq() - comes from
client_checks.stage, which builds the one staging tree at import.
"""
import ast

from client_checks.stage import (SRC, SRC_FILES, bad, head, ok)


def _geometry_calls(src):
    """Every .geometry() call in one source, by AST rather than by shape.

    Never by grep. A sweep for geometry("<W>x<H>") is exactly what hid the
    sixth Server GUI dialog, whose height was computed - so the calls are
    walked and their arguments read.
    """
    tree = ast.parse(src)
    owner = {}

    def path(node, name):
        for child in ast.iter_child_nodes(node):
            nxt = name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                nxt = (name + "." if name else "") + child.name
            owner[child] = nxt
            path(child, nxt)
    path(tree, "")
    return [(owner.get(n, "<module>"), n) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "geometry"]


def check_no_client_window_takes_its_size_from_a_branch():
    """No window's size may be conditional on what is in it.

    `'400x%d' % (350 if confirmed else 290)` is wrong in at least one branch by
    construction - it was short in both - and no sweep for geometry literals
    can see it, which is why the Server GUI's Cancel Transaction survived the
    first pass over that file. Two were here: that one, and the Dashboard's
    `'1140x740' if see_all else '1080x740'`.

    If the size depends on what is in the window, ask the window.
    """
    head("no client window takes its size from a branch")
    for name in SRC_FILES:
        calls = _geometry_calls(SRC[name])
        branched = [(where, node) for where, node in calls
                    if any(isinstance(x, ast.IfExp)
                           for a in node.args for x in ast.walk(a))]
        for where, node in branched:
            bad("%s: %s sizes its window from a branch - %s"
                % (name, where,
                   ast.unparse(node.args[0]) if node.args else ""))
        # Guarded, the way the group below guards its own. An unconditional
        # summary printed a pass beside the failure it had just reported, and a
        # gate that contradicts itself in the same breath is read for its
        # kinder half.
        if not branched:
            ok("%s: %d geometry call(s), none conditional"
               % (name, len(calls)))


def check_only_ui_kit_sizes_a_client_window():
    """One `fit`, in the kit. Never a copy in an app.

    The three apps used to hold byte-identical copies of the transport layer
    and rule 10 is what that cost; the same argument applies to a window
    helper, one file up. `ui_kit.py` already ships to every machine that runs
    one of these windows - bundle-client.ps1 stages it beside installer.py and
    package.ps1 stages it beside server.py - so there is nowhere for a
    second copy to be justified.
    """
    head("only ui_kit sizes a client window")
    for name in SRC_FILES:
        tree = ast.parse(SRC[name])
        local = [n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in ("fit", "_fit")]
        if local:
            bad("%s defines its own %s - ui_kit.fit is the one copy"
                % (name, ", ".join(local)))
        loose = [ast.unparse(n) for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id in ("fit", "_fit")]
        if loose:
            bad("%s calls %s, which is not ui_kit.fit"
                % (name, ", ".join(loose)))
        kit = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "fit"
               and getattr(n.func.value, "id", "") == "ui_kit"]
        if not local and not loose:
            ok("%s: %d ui_kit.fit call(s), no copy of its own"
               % (name, len(kit)))
