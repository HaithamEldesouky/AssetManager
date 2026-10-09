r"""The Notifier's one window taller than a 768px screen, and the recorder
that judges it (095).

`stage.py` wraps the staged `ui_kit.fit` and judges every window at the call:
one asking more than 688px that does not scroll is a failure there and then,
whichever group opened it. This group is what keeps that from quietly
stopping - it opens Remote Admin on its Mail panel, the tallest one and
over the line when the recorder went in, and asserts the recorder saw it
by title. A recorder that measured nothing would otherwise pass by finding
nothing.
"""
from client_checks.stage import FIT_SEEN, NR, bad, eq, head, tk_or_skip


def check_the_windows_taller_than_the_screen_are_measured():
    """Remote Admin, opened on its Mail panel, by title.

    Opened with `opens` handed in, which is `_open_with` straight away - the
    locked form's own `fit` never runs, so the title being seen at all is the
    opened console being measured.
    """
    head("the windows taller than the screen are measured (095)")
    tk = tk_or_skip()
    if tk is None:
        return

    class _Answer(object):
        def __init__(self, status, body):
            self.status_code, self._body = status, body
            self.ok = 200 <= status < 300

        def json(self):
            return self._body

    # What each panel reads when it is drawn, so the console is measured
    # holding something: offline, every panel draws its empty state and the
    # window opens under the line it crosses with a server behind it.
    table = {
        "/admin/server_config": _Answer(200, {"host": "0.0.0.0",
                                              "port": 8081}),
        "/admin/mail": _Answer(200, {"host": "relay.example", "port": 25,
                                     "from": "assets@example",
                                     "username": "", "starttls": True,
                                     "password_stored": True,
                                     "can_store": True}),
        "/assets/proposals": _Answer(200, []),
        "/clients": _Answer(200, {"clients": [], "served": "",
                                  "staged": ""}),
        "/permissions": _Answer(200, [{"name": "view_all_history",
                                       "label": "Sees every history"}]),
        "/members": _Answer(200, [
            {"id": 1, "name": "Brian Dawson", "auto_approve": False,
             "profile": "default", "permissions": [], "has_password": True,
             "must_change_password": False}]),
    }

    def _api(method, url, **kw):
        for frag, answer in table.items():
            if frag in url:
                return answer
        return _Answer(200, [])

    root = tk.Tk()
    root.withdraw()
    FIT_SEEN.pop("Remote Admin", None)
    saved, NR.api = NR.api, _api
    try:
        w = NR.RemoteAdminWindow(root, "http://127.0.0.1:1",
                                 opens=("mail",), config={})
        root.update_idletasks()
        root.update()
        w.win.destroy()
    except Exception as e:
        bad("Remote Admin did not open: %s" % e)
    finally:
        NR.api = saved
    eq("the recorder saw Remote Admin", "Remote Admin" in FIT_SEEN, True)
    try:
        root.destroy()
    except Exception:
        pass
