"""Program shell: a left rail (project, subjects, sub-sections) and a ribbon of grouped commands above the working area.

The existing tab pages are not rebuilt. Their tab bars are hidden and the rail and ribbon drive them, so every feature,
shortcut and saved setting stays as it was. Colours follow the program's dark / light mode."""
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

# main tab index -> (rail label, icon name); order of the main tabs in the window
SUBJECTS = [(0, "Overview", "home"), (6, "Drawing register", "clipboard"), (1, "Light && ventilation", "lightvent"), (2, "Energy (XA)", "bolt"),
            (3, "Coverage && FAR", "building"), (4, "Detail notes", "ruler"), (5, "Costing", "tag")]
LV_SUBS = [(0, "Windows", "window"), (1, "Doors", "door"), (2, "Rooms", "room"), (3, "Results", "results"), (4, "Plan", "plan")]


def _palette(is_light):
    if is_light:
        return dict(rail="#eceef1", ribbon="#f3f4f6", line="#d4d7dc", text="#1c1f24", muted="#59616b", hover="#e1e4e8",
                    sel="#fbe3e6", accent="#c4162a", hot="#fbe3e6", hotline="#e8a7af", card="#ffffff")
    return dict(rail="#131316", ribbon="#131316", line="#26262c", text="#eceef0", muted="#9aa0a8", hover="#1f1f24",
                sel="#241619", accent="#e0243a", hot="#3a161d", hotline="#7a1c29", card="#17171b")


def _qss(p):
    return f"""
    QFrame#shellRail {{ background:{p['rail']}; border-right:1px solid {p['line']}; }}
    QFrame#shellRibbon {{ background:{p['ribbon']}; border-bottom:1px solid {p['line']}; }}
    QLabel#railTitle {{ font-size:17px; font-weight:700; color:{p['text']}; }}
    QLabel#railSub {{ font-size:12px; color:{p['muted']}; }}
    QPushButton#railNav {{ text-align:left; padding:0 12px; height:40px; border-radius:10px; border:0; background:transparent;
        color:{p['text']}; font-size:13.5px; font-weight:500; }}
    QPushButton#railNav:hover {{ background:{p['hover']}; }}
    QPushButton#railNav[on="true"] {{ background:{p['sel']}; font-weight:700; border-left:3px solid {p['accent']}; border-radius:6px; }}
    QPushButton#railSubItem {{ text-align:left; padding:0 12px 0 30px; height:32px; border-radius:8px; border:0; background:transparent;
        color:{p['muted']}; font-size:13px; }}
    QPushButton#railSubItem:hover {{ background:{p['hover']}; }}
    QPushButton#railSubItem[on="true"] {{ background:{p['hover']}; color:{p['text']}; font-weight:700; }}
    QLabel#railBadge {{ color:{p['muted']}; font-size:12px; }}
    QPushButton#railPack {{ background:{p['accent']}; color:white; border:1px solid {p['accent']}; border-radius:9px; height:38px;
        font-weight:700; }}
    QToolButton#ribTool {{ min-width:62px; padding:6px 8px; border-radius:9px; border:1px solid transparent; background:transparent;
        color:{p['text']}; font-size:12px; }}
    QToolButton#ribTool:hover {{ background:{p['hover']}; }}
    QToolButton#ribTool[hot="true"] {{ background:{p['hot']}; border:1px solid {p['hotline']}; }}
    QLabel#ribCap {{ color:{p['muted']}; font-size:11px; }}
    QFrame#ribDiv {{ background:{p['line']}; max-width:1px; min-width:1px; }}
    """


class Rail(QFrame):
    def __init__(self, win, make_icon=None, light_fn=None):
        super().__init__()
        self.win, self.make_icon, self.light_fn = win, make_icon, light_fn
        self.setObjectName("shellRail")
        self.setFixedWidth(224)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 14, 10, 12)
        v.setSpacing(3)
        self.title = QLabel("Unnamed project")
        self.title.setObjectName("railTitle")
        self.title.setWordWrap(True)
        self.sub = QLabel("")
        self.sub.setObjectName("railSub")
        self.sub.setWordWrap(True)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        v.addSpacing(10)
        self.nav, self.badge, self.subs = {}, {}, {}
        for idx, label, _icon in SUBJECTS:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            b = QPushButton(label)
            b.setObjectName("railNav")
            b.setProperty("iconName", _icon)
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, i=idx: win.main_tabs.setCurrentIndex(i))
            bd = QLabel("")
            bd.setObjectName("railBadge")
            hl.addWidget(b, 1)
            hl.addWidget(bd)
            v.addWidget(row)
            self.nav[idx], self.badge[idx] = b, bd
            if idx == 1:
                for si, sl, sic in LV_SUBS:
                    sb = QPushButton(sl)
                    sb.setObjectName("railSubItem")
                    sb.setProperty("iconName", sic)
                    sb.setIconSize(QSize(16, 16))
                    sb.setCursor(Qt.CursorShape.PointingHandCursor)
                    sb.clicked.connect(lambda _c=False, i=si: self._lv_sub(i))
                    v.addWidget(sb)
                    self.subs[si] = sb
        v.addStretch(1)
        self.pack = QPushButton("Build submission pack")
        self.pack.setObjectName("railPack")
        self.pack.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pack.setToolTip("Opens the project dashboard for the Detail Notes folder you last ran.")
        self.pack.clicked.connect(self._pack)
        v.addWidget(self.pack)

    def icons(self):
        if not self.make_icon:
            return
        col = "#1c1f24" if self.light_fn() else "#eceef0"
        for b in self.findChildren(QPushButton):
            n = b.property("iconName")
            if n:
                b.setIcon(self.make_icon(n, col, 20))

    def _lv_sub(self, i):
        self.win.main_tabs.setCurrentIndex(1)
        self.win.tabs.setCurrentIndex(i)

    def _pack(self):
        w = self.win
        d = getattr(w, "_det_win", None)
        w.main_tabs.setCurrentIndex(4)
        if d is not None and getattr(d, "proj_data", None):
            try:
                d.show_project()
            except Exception:
                pass

    def sync(self):
        cur = self.win.main_tabs.currentIndex()
        for idx, b in self.nav.items():
            on = "true" if idx == cur else "false"
            if b.property("on") != on:
                b.setProperty("on", on)
                b.style().unpolish(b)
                b.style().polish(b)
        lvi = self.win.tabs.currentIndex()
        for i, sb in self.subs.items():
            on = "true" if (cur == 1 and i == lvi) else "false"
            if sb.property("on") != on:
                sb.setProperty("on", on)
                sb.style().unpolish(sb)
                sb.style().polish(sb)
            sb.setVisible(cur == 1)


class Ribbon(QFrame):
    def __init__(self, win, make_icon, light_fn):
        super().__init__()
        self.win, self.make_icon, self.light_fn = win, make_icon, light_fn
        self.setObjectName("shellRibbon")
        self.setFixedHeight(92)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self.pages = {}
        self._build()

    def _tool(self, text, icon, fn, hot=False):
        b = QToolButton()
        b.setObjectName("ribTool")
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(24, 24))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setProperty("hot", "true" if hot else "false")
        b.setProperty("iconName", icon)
        b.clicked.connect(lambda _c=False, f=fn: f())
        return b

    def _group(self, caption, tools):
        g = QWidget()
        gv = QVBoxLayout(g)
        gv.setContentsMargins(10, 6, 10, 2)
        gv.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(4)
        for t in tools:
            row.addWidget(t)
        gv.addLayout(row, 1)
        c = QLabel(caption)
        c.setObjectName("ribCap")
        c.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gv.addWidget(c)
        return g

    def _page(self, groups):
        p = QWidget()
        h = QHBoxLayout(p)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(0)
        first = True
        for cap, tools in groups:
            if not first:
                d = QFrame()
                d.setObjectName("ribDiv")
                h.addWidget(d)
            first = False
            h.addWidget(self._group(cap, tools))
        h.addStretch(1)
        return p

    def _build(self):
        w = self.win
        T = self._tool

        def go_lv(i):
            return lambda: (w.main_tabs.setCurrentIndex(1), w.tabs.setCurrentIndex(i))

        def call(name, *a, **k):
            def f():
                fn = getattr(w, name, None)
                if fn:
                    fn(*a, **k)
            return f
        def project():
            return ("Project", [T("New", "add", call("new_project")), T("Open", "folder", call("open_project")),
                                T("Save", "save", call("save_project")),
                                T("Details", "edit", call("project_wizard", editing=True))])

        def model():
            return ("Model", [T("Import IFC", "cube", call("import_ifc"))])

        def allsub(kind):
            return lambda: getattr(w, "export_subject_pdfs", lambda *_: None)(kind)
        self.pages[0] = self._page([project(), model()])
        self.pages[1] = self._page([
            ("Model", [T("Import IFC", "cube", call("import_ifc")), T("Windows", "window", go_lv(0)),
                       T("Doors", "door", go_lv(1)), T("Rooms", "room", go_lv(2)), T("Plan", "plan", go_lv(4))]),
            ("Check", [T("Run check", "shield", call("run_check"), hot=True), T("Results", "results", go_lv(3))]),
            ("Reports", [T("Preview PDF", "eye", call("preview_pdf_report")), T("Export PDF", "pdf", call("export_pdf_report")),
                         T("All subjects", "layers", allsub("lv"))])])

        def xa_run():
            fn = getattr(w, "_run_xa", None)
            if fn:
                fn()

        def xa_prev():
            if hasattr(w, "_write_xa_pdf"):
                w.preview_pdf_report(w._write_xa_pdf, getattr(w, "_run_xa", lambda: None))

        def sections(tab_index, label):
            """A tool with a menu that scrolls the tab to one of its framed sections."""
            from PySide6.QtWidgets import QMenu, QScrollArea, QGroupBox
            b = self._tool(label, "layers", lambda: None)
            m = QMenu(b)

            def fill():
                m.clear()
                page = w.main_tabs.widget(tab_index)
                for g in page.findChildren(QGroupBox):
                    if not g.title() or not g.isVisibleTo(page):
                        continue
                    a = m.addAction(g.title().replace("&&", "&"))
                    a.triggered.connect(lambda _c=False, gb=g: self._jump(gb))
            m.aboutToShow.connect(fill)
            b.setMenu(m)
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            return b

        self.pages[2] = self._page([project(), model(),
                                    ("Check", [T("Run XA check", "shield", xa_run, hot=True),
                                               T("Report details", "edit", call("rd_dialog")),
                                               sections(2, "Sections")]),
                                    ("Reports", [T("Preview", "eye", xa_prev), T("Export PDF", "pdf", call("export_xa_pdf")),
                                                 T("All subjects", "layers", allsub("xa"))])])

        def cov_prev():
            if hasattr(w, "_write_cov_pdf"):
                w.preview_pdf_report(w._write_cov_pdf, lambda: None)
        self.pages[3] = self._page([project(),
                                    ("Calculate", [T("Fill from rooms", "room", lambda: w.cov_fill_from_rooms(True), hot=True)]),
                                    ("Reports", [T("Preview", "eye", cov_prev), T("Export PDF", "pdf", call("export_cov_pdf")),
                                                 T("Each calculation", "layers", allsub("cov")),
                                                 T("Site sheets", "building", call("export_cov_sheets"))])])

        def det(name):
            def f():
                d = getattr(w, "_det_win", None)
                if d is None:
                    return
                w.main_tabs.setCurrentIndex(4)
                fn = getattr(d, name, None)
                if fn:
                    fn()
            return f

        def det_btn(attr):
            def f():
                d = getattr(w, "_det_win", None)
                b = getattr(d, attr, None) if d is not None else None
                w.main_tabs.setCurrentIndex(4)
                if b is not None and b.isEnabled():
                    b.click()
            return f
        self.pages[4] = self._page([
            ("Detail", [T("Open DWG / DXF", "folder", det("pick_file"), hot=True), T("Settings", "settings", det("settings")),
                        T("Outputs", "pdf", det("open_outputs"))]),
            ("Notes", [T("Auto note", "play", det_btn("btn_auto")), T("Next problem", "search", det("next_problem")),
                       T("Undo", "refresh", det("undo_user")), T("Redo", "copy", det("redo_user"))]),
            ("Project", [T("Dashboard", "clipboard", det("show_project")), T("Batch folder", "layers", det("batch_folder")),
                         T("Notes schedule", "pdf", det("export_schedule"))])])
        def cost(name, *a):
            def f():
                c = getattr(w, "costing_page", None)
                if c is None:
                    return
                w.main_tabs.setCurrentIndex(5)
                getattr(c, name)(*a)
            return f
        self.pages[5] = self._page([
            ("Schedule", [T("Build from rooms", "room", cost("build_from_rooms"), hot=True), T("Add line", "add", cost("add_line"))]),
            ("Products", [T("From link", "import", cost("add_from_link")), T("Manual", "edit", cost("add_product")),
                          T("Find product", "search", cost("find_ai"), hot=True)]),
            ("Building materials", [T("Read IFC", "cube", cost("mat_read")), T("Preview", "eye", cost("mat_preview")), T("Export", "pdf", cost("mat_export"))]),
            ("Reports", [T("Preview PDF", "eye", cost("preview_pdf")), T("Export PDF", "pdf", cost("export_pdf")), T("Export CSV", "export", cost("export_csv"))])])
        def reg(name, *a):
            def f():
                c = getattr(w, "register_page", None)
                if c is None:
                    return
                w.main_tabs.setCurrentIndex(6)
                getattr(c, name)(*a)
            return f
        self.pages[6] = self._page([
            ("Drawings", [T("Add PDFs", "add", reg("add_pdfs"), hot=True), T("Add folder", "folder", reg("add_folder")), T("Re-read PDFs", "refresh", reg("reread")), T("New group", "layers", reg("add_group")),
                          T("Remove", "trash", reg("remove_row"))]),
            ("Email", [T("Write email", "edit", reg("write_mail"), hot=True), T("Mark as issued", "check_circle", reg("mark_issued")), T("Copy", "copy", reg("copy_mail")), T("Open in email", "export", reg("open_mail"))]),
            ("Register", [T("Preview PDF", "eye", reg("preview_pdf")), T("Export PDF", "pdf", reg("export_pdf")), T("Export CSV", "export", reg("export_csv"))])])
        for i in sorted(self.pages):
            self.stack.addWidget(self.pages[i])
        self.icon_names()

    def icon_names(self):
        col = "#1c1f24" if self.light_fn() else "#eceef0"
        for b in self.findChildren(QToolButton):
            n = b.property("iconName")
            if n:
                b.setIcon(self.make_icon(n, col, 24))

    def _jump(self, gb):
        from PySide6.QtWidgets import QScrollArea
        p = gb.parentWidget()
        while p is not None and not isinstance(p, QScrollArea):
            p = p.parentWidget()
        if p is not None:
            p.ensureWidgetVisible(gb, 0, 20)
            p.verticalScrollBar().setValue(max(0, gb.mapTo(p.widget(), gb.rect().topLeft()).y() - 8))

    def show_for(self, idx):
        self.stack.setCurrentIndex(idx if idx in self.pages else 0)
        self.setVisible(True)


def install_shell(win, make_icon, light_fn):
    """Put the rail and ribbon around the window's main tabs. Safe to call once."""
    central = win.centralWidget()
    lay = central.layout()
    mt = win.main_tabs
    lay.removeWidget(mt)
    lay.setContentsMargins(0, 0, 0, 0)
    body = QWidget()
    hb = QHBoxLayout(body)
    hb.setContentsMargins(0, 0, 0, 0)
    hb.setSpacing(0)
    rail = Rail(win, make_icon, light_fn)
    right = QWidget()
    rv = QVBoxLayout(right)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(0)
    ribbon = Ribbon(win, make_icon, light_fn)
    rv.addWidget(ribbon)
    rv.addWidget(mt, 1)
    hb.addWidget(rail)
    hb.addWidget(right, 1)
    lay.addWidget(body, 1)
    mt.tabBar().hide()
    win.tabs.tabBar().hide()
    win.shell_rail, win.shell_ribbon, win.shell_body = rail, ribbon, body
    state = {"light": None}

    def restyle():
        is_l = bool(light_fn())
        if state["light"] != is_l:
            state["light"] = is_l
            body.setStyleSheet(_qss(_palette(is_l)))
            ribbon.icon_names()
            rail.icons()

    def refresh():
        restyle()
        cur = mt.currentIndex()
        ribbon.show_for(cur)
        rail.sync()
        rd = getattr(win, "rd", {}) or {}
        rail.title.setText((rd.get("project") or "").strip() or "Unnamed project")
        rail.sub.setText((rd.get("details") or "").strip() or "Add the site in Project details")
        res = getattr(win, "results", None) or []
        if res:
            ok = sum(1 for r in res if r.get("light_ok") and r.get("vent_ok"))
            rail.badge[1].setText("%d / %d" % (ok, len(res)))
        else:
            rail.badge[1].setText("")
        rail.setVisible(win.width() >= 900)

    mt.currentChanged.connect(lambda _i: refresh())
    win.tabs.currentChanged.connect(lambda _i: refresh())
    t = QTimer(win)
    t.timeout.connect(refresh)
    t.start(1500)
    win._shell_timer = t
    rail.icons()
    restyle()
    refresh()
    return rail, ribbon
