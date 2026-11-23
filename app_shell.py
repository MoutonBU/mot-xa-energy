"""Program shell: a left rail (project, subjects, sub-sections) and a ribbon of grouped commands above the working area.

The existing tab pages are not rebuilt. Their tab bars are hidden and the rail and ribbon drive them, so every feature,
shortcut and saved setting stays as it was. Colours follow the program's dark / light mode."""
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

# main tab index -> (rail label, icon name); order of the main tabs in the window
SUBJECTS = [(0, "Project", "home"), (6, "Drawing register", "clipboard"), (10, "Orders", "tag"), (11, "Invoicing", "calc"), (1, "Light && ventilation", "lightvent"), (2, "Energy (XA)", "bolt"), (13, "Rational design", "shield"),
            (3, "Coverage && FAR", "building"), (4, "Detail notes", "ruler"), (5, "Costing", "tag"),
            (7, "Area schedule", "layers"), (8, "Building lines", "land"), (12, "House placing", "land"), (9, "Guidelines review", "clipboard")]
CTX = {13: "sans", 11: "invoicing", 10: "orders", 1: "sans", 2: "sans", 3: "sans", 4: "detail", 5: "costing", 6: "register", 7: "site", 8: "site", 9: "rules", 12: "site"}      # which tool a main tab belongs to
PSUB_ICONS = {"Drawings": "clipboard", "Orders": "tag", "Client changes": "edit", "Sent and revisions": "export",
              "Fixtures and sanitary ware": "drop", "Building materials": "layers", "Whole building and budget": "calc"}
LV_SUBS = [(0, "Windows", "window"), (1, "Doors", "door"), (2, "Rooms", "room"), (3, "Results", "results"), (4, "Plan", "plan")]


def _palette(is_light):
    if is_light:
        return dict(rail="#eceef1", ribbon="#f3f4f6", line="#d4d7dc", text="#1c1f24", muted="#59616b", hover="#e1e4e8",
                    sel="#fbe3e6", accent="#c4162a", hot="#fbe3e6", hotline="#e8a7af", card="#ffffff")
    return dict(rail="#131316", ribbon="#131316", line="#26262c", text="#eceef0", muted="#9aa0a8", hover="#1f1f24",
                sel="#241619", accent="#e0243a", hot="#3a161d", hotline="#7a1c29", card="#17171b")


def _qss(p):
    return f"""
    QFrame#shellRail {{ background:{p['rail']}; border:1px solid {p['line']}; border-radius:14px; }}
    QFrame#shellRibbon {{ background:{p['ribbon']}; border:1px solid {p['line']}; border-radius:14px; }}
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
        hb_ = QPushButton("\u2039  Home")
        hb_.setObjectName("railNav")
        hb_.setCursor(Qt.CursorShape.PointingHandCursor)
        hb_.setToolTip("Back to the four squares")
        hb_.clicked.connect(lambda _c=False: win.main_tabs.setCurrentIndex(win.launcher_idx[0]))
        sw_ = QPushButton("Switch tool  \u25BE")
        sw_.setObjectName("railNav")
        sw_.setCursor(Qt.CursorShape.PointingHandCursor)
        sw_.setToolTip("Jump straight to another tool")
        sw_.clicked.connect(lambda _c=False, b=sw_: self._switch_menu(b))
        hr_ = QHBoxLayout()
        hr_.setSpacing(4)
        hr_.addWidget(hb_)
        hr_.addWidget(sw_, 1)
        v.addLayout(hr_)
        v.addSpacing(6)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        v.addSpacing(10)
        from PySide6.QtWidgets import QScrollArea
        navw = QWidget()
        navw.setObjectName("railNavBox")
        nv = QVBoxLayout(navw)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(3)
        navsc = QScrollArea()                       # on a short window the menu scrolls; the pack button below stays in view
        navsc.setWidgetResizable(True)
        navsc.setFrameShape(QFrame.Shape.NoFrame)
        navsc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navsc.setStyleSheet("QScrollArea{background:transparent;} #railNavBox{background:transparent;} QScrollBar:vertical{width:6px;}")
        navsc.setWidget(navw)
        v.addWidget(navsc, 1)
        self.nav, self.badge, self.subs, self.rows, self.psubs = {}, {}, {}, {}, {}
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
            if idx == 13:                           # not a tab: runs the built-in rational design simulation
                b.setToolTip("Simulate the building for a year against the reference building (SANS 10400-XA rational design)")
                b.clicked.connect(lambda _c=False: win.rational_design_dialog())
            else:
                b.clicked.connect(lambda _c=False, i=idx: win.main_tabs.setCurrentIndex(i))
            bd = QLabel("")
            bd.setObjectName("railBadge")
            hl.addWidget(b, 1)
            hl.addWidget(bd)
            nv.addWidget(row)
            self.nav[idx], self.badge[idx] = b, bd
            self.rows[idx] = row
            if idx == 1:
                for si, sl, sic in LV_SUBS:
                    sb = QPushButton(sl)
                    sb.setObjectName("railSubItem")
                    sb.setProperty("iconName", sic)
                    sb.setIconSize(QSize(16, 16))
                    sb.setCursor(Qt.CursorShape.PointingHandCursor)
                    sb.clicked.connect(lambda _c=False, i=si: self._lv_sub(i))
                    nv.addWidget(sb)
                    self.subs[si] = sb
            tw = self._inner_tabs(idx)
            if tw is not None:
                tw.tabBar().hide()              # the sections of this tool are listed in the bar instead of along the top
                self.psubs[idx] = []
                for ti in range(tw.count()):
                    lbl = tw.tabText(ti)
                    sb = QPushButton({"Fixtures and sanitary ware": "Fixtures", "Whole building and budget": "Whole building"}.get(lbl, lbl).replace("&&", "&"))
                    sb.setObjectName("railSubItem")
                    sb.setProperty("iconName", PSUB_ICONS.get(lbl, "folder"))
                    sb.setIconSize(QSize(16, 16))
                    sb.setCursor(Qt.CursorShape.PointingHandCursor)
                    sb.clicked.connect(lambda _c=False, i=idx, t=ti, w_=tw: (win.main_tabs.setCurrentIndex(i), w_.setCurrentIndex(t)))
                    nv.addWidget(sb)
                    self.psubs[idx].append(sb)
                tw.currentChanged.connect(lambda _i: self.sync())
        nv.addStretch(1)
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
                b.setIcon(self.make_icon(n, col, 28))              # drawn larger than shown, so it stays sharp while it grows under the pointer
        if not getattr(self, "_hover_filter", None):
            from PySide6.QtCore import QEvent, QObject

            rail = self

            class _Hover(QObject):
                """a bar icon turns red while it is pointed at (it also grows: see ui_extras.IconMotion)"""
                def eventFilter(self, obj, ev):
                    try:
                        t = ev.type()
                        n_ = obj.property("iconName") if isinstance(obj, QPushButton) else None
                        if n_ and t in (QEvent.Type.Enter, QEvent.Type.Leave):
                            c_ = "#ff4056" if t == QEvent.Type.Enter else ("#1c1f24" if rail.light_fn() else "#eceef0")
                            obj.setIcon(rail.make_icon(n_, c_, 28))
                    except Exception:
                        pass
                    return False
            self._hover_filter = _Hover(self)
            # the red hover now comes from ui_extras.IconMotion for every icon button

    def _inner_tabs(self, idx):
        """The tab widget inside the Drawing register (6) or the Costing (5), whose sections the bar lists."""
        pg = getattr(self.win, "orders_page" if idx == 10 else "register_page" if idx == 6 else "costing_page" if idx == 5 else "", None) if idx in (5, 6, 10) else None
        tw = getattr(pg, "sub" if idx in (6, 10) else "main", None) if pg is not None else None
        return tw

    def _switch_menu(self, btn):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        w = self.win
        col = "#1c1f24" if self.light_fn() else "#eceef0"
        for label, idx, ico in (("Drawing register", 6, "clipboard"), ("Orders", 10, "tag"), ("Invoicing", 11, "calc"), ("Detail tool", 4, "ruler"), ("Costing", 5, "calc"), (None, None, None),
                                ("Light && Ventilation", 1, "lightvent"), ("Energy (XA)", 2, "bolt"), ("Coverage && FAR", 3, "building"), (None, None, None),
                                ("Building lines", 8, "land"), ("House placing", 12, "land"), ("Area schedule", 7, "layers"), ("Guidelines review", 9, "clipboard"), (None, None, None),
                                ("Home (the four squares)", -1, "home")):
            if label is None:
                m.addSeparator()
                continue
            a = m.addAction(label.replace("&&", "&"), lambda i=idx: w.main_tabs.setCurrentIndex(w.launcher_idx[0] if i < 0 else i))
            if self.make_icon:
                a.setIcon(self.make_icon(ico, col, 20))
        m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

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
        w_ = self.win
        if cur in CTX:
            w_._ctx = CTX[cur]
        elif cur in (getattr(w_, "launcher_idx", None) or ()):
            w_._ctx = None
        ctx = getattr(w_, "_ctx", None)
        for idx, row in self.rows.items():
            row.setVisible((ctx != "detail") if idx == 0 else (CTX.get(idx) == ctx))
        self.pack.setVisible(ctx == "detail")
        for idx, btns in self.psubs.items():
            tw = self._inner_tabs(idx)
            for i, sb in enumerate(btns):
                sb.setVisible(cur == idx and (tw is None or tw.isTabVisible(i)))      # a shelved section stays out of the list
                on = "true" if (cur == idx and tw is not None and tw.currentIndex() == i) else "false"
                if sb.property("on") != on:
                    sb.setProperty("on", on)
                    sb.style().unpolish(sb)
                    sb.style().polish(sb)
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
        from PySide6.QtWidgets import QScrollArea
        sc = QScrollArea()                              # on a narrow window the ribbon scrolls sideways instead of overlapping its labels
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sc.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;} QScrollBar:horizontal{height:6px;}")
        sc.setWidget(self.stack)
        v.addWidget(sc)
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
                st_ = getattr(w, "xa_steps", None) if tab_index == 2 else None
                for g in (st_.boxes if st_ is not None else page.findChildren(QGroupBox)):
                    if not g.title() or (st_ is None and not g.isVisibleTo(page)):
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
            ("Schedule", [T("Rooms", "room", cost("build_from_rooms"), hot=True), T("Add line", "add", cost("add_line"))]),
            ("Products", [T("From link", "import", cost("add_from_link")), T("Manual", "edit", cost("add_product")),
                          T("Find (AI)", "search", cost("find_ai"), hot=True)]),
            ("Building materials", [T("Read IFC", "cube", cost("mat_read")), T("Preview", "eye", cost("mat_preview")), T("Export", "pdf", cost("mat_export"))]),
            ("Costing report", [T("Preview", "eye", cost("cost_report_preview"), hot=True), T("PDF", "pdf", cost("cost_report_export"))]),
            ("Fixture schedule", [T("Preview", "eye", cost("preview_pdf")), T("PDF", "pdf", cost("export_pdf")), T("CSV", "export", cost("export_csv"))])])
        def reg(name, *a):
            def f():
                c = getattr(w, "register_page", None)
                if c is None:
                    return
                w.main_tabs.setCurrentIndex(6)
                getattr(c, name)(*a)
            return f
        self.pages[6] = self._page([
            ("Drawings", [T("Add files", "add", reg("add_pdfs"), hot=True), T("Add folder", "folder", reg("add_folder")), T("Remove", "trash", reg("remove_row"))]),
            ("Send", [T("Send to client", "export", reg("send_mail"), hot=True), T("Email account", "settings", reg("email_account"))]),
            ("PDF", [T("Preview", "eye", reg("preview_pdf")), T("Save PDF", "pdf", reg("export_pdf"))])])
        def ordr(name, *a):
            def f():
                c = getattr(w, "register_page", None)
                if c is None:
                    return
                c.show_orders("Change" if (name == "changes_from_drawings" or a == ("Change",)) else "Order")
                getattr(c, name)(*a)
            return f
        def ordr_more():
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor
            c = getattr(w, "register_page", None)
            if c is None:
                return
            c.show_orders("Order")
            m = QMenu(w)
            m.addAction("Attach the client's email to the selected line...", lambda: c.attach_ref())
            m.addAction("Open the client's email", lambda: c.open_ref())
            m.addAction("Remove the selected line", lambda: c.remove_log())
            m.addSeparator()
            m.addAction("My email signature...", lambda: c.my_signature())
            m.addAction("Text size...", lambda: c.orders_text_size())
            m.addAction("Back up the orders...", lambda: c.orders_backup())
            m.addAction("Restore from a backup...", lambda: c.orders_restore())
            m.addAction("Delete all orders...", lambda: c.delete_all_log("Order"))
            m.exec(QCursor.pos())
        def invo(name, *a):
            def f():
                c = getattr(w, "invoicing_page", None)
                if c is None:
                    return
                w.main_tabs.setCurrentIndex(11)
                getattr(c, name)(*a)
            return f
        self.pages[11] = self._page([
            ("Invoices", [T("New invoice", "add", invo("new_invoice"), hot=True), T("Edit", "edit", invo("edit_invoice")), T("Copy", "layers", invo("copy_invoice"))]),
            ("PDF", [T("Preview", "eye", invo("preview"), hot=True), T("Save PDF", "pdf", invo("save_pdf"))]),
            ("Status", [T("Paid / unpaid", "tag", invo("toggle_paid")), T("Delete", "trash", invo("delete_invoice"))]),
            ("Setup", [T("My business", "settings", invo("business")), T("Who can use", "clipboard", invo("manage_access")), T("Lock", "eye", invo("lock"))])])
        self.pages[10] = self._page([
            ("Gmail", [T("Watch inbox", "clipboard", ordr("inbox_dialog"), hot=True), T("Check now", "refresh", ordr("inbox_check_now"))]),
            ("Orders", [T("New order", "add", ordr("new_order"), hot=True), T("Search", "search", ordr("orders_search")), T("More", "settings", ordr_more)]),
            ("Help", [T("Setup guide", "clipboard", ordr("setup_guide")), T("Help", "eye", ordr("orders_help"))])])
        def tool(attr, name, *a):
            def f():
                c = getattr(w, attr, None)
                if c is None:
                    return
                getattr(c, name)(*a)
            return f

        def step(attr, i):
            def f():
                c = getattr(w, attr, None)
                if c is not None:
                    c.steps.go(i)
            return f
        self.pages[7] = self._page([
            ("Rooms", [T("From project", "room", tool("area_page", "fill_project"), hot=True), T("IFC", "cube", tool("area_page", "fill_ifc")),
                       T("Import", "import", tool("area_page", "import_csv")), T("Paste", "clipboard", tool("area_page", "paste_rows")),
                       T("Add", "add", tool("area_page", "add_row"))]),
            ("Totals", [T("Totals", "results", step("area_page", 1))]),
            ("Reports", [T("Preview", "eye", tool("area_page", "preview"), hot=True), T("PDF", "pdf", tool("area_page", "export")),
                         T("CSV", "export", tool("area_page", "export_csv"))])])
        self.pages[8] = self._page([
            ("Survey", [T("Load", "land", tool("site_page", "load_drawing", "site"), hot=True), T("Pick", "land", tool("site_page", "pick_shape", "site", "stand")),
                        T("Trace", "land", tool("site_page", "start_trace", "trace_stand", "site"))]),
            ("Footprint", [T("IFC", "cube", tool("site_page", "footprint_from_ifc")), T("Drawing", "pdf", tool("site_page", "load_drawing", "fp")),
                           T("Trace", "land", tool("site_page", "start_trace", "trace_building", "fp"))]),
            ("Stand", [T("Rectangle", "land", tool("site_page", "make_rect")), T("Apply lines", "check_circle", tool("site_page", "apply_quick"))]),
            ("Buildings", [T("Add", "add", tool("site_page", "add_building")), T("Centre", "pin", tool("site_page", "centre_building")), T("Ruler", "ruler", tool("site_page", "place_with_ruler")),
                           T("Result", "results", step("site_page", 2))]),
            ("Reports", [T("Preview", "eye", tool("site_page", "preview"), hot=True), T("PDF", "pdf", tool("site_page", "export"))])])
        self.pages[9] = self._page([
            ("Rules", [T("Usual rules", "add", tool("guidelines_page", "add_usual"), hot=True), T("Add", "add", tool("guidelines_page", "add_rule")),
                       T("Remove selected", "trash", tool("guidelines_page", "remove_rule")),
                       T("Select all", "check_circle", tool("guidelines_page", "select_all_rules"))]),
            ("Review", [T("Measure", "results", step("guidelines_page", 1), hot=True), T("Show on plan", "eye", tool("guidelines_page", "show_on_plan"))]),
            ("Reports", [T("Preview", "eye", tool("guidelines_page", "preview")), T("PDF", "pdf", tool("guidelines_page", "export"))])])
        self.pages[12] = self._page([
            ("Stand", [T("Rectangle", "land", tool("services_page", "make_rect")), T("From Building lines", "land", tool("services_page", "from_site_page"), hot=True),
                       T("Suggest", "pin", tool("services_page", "suggest"))]),
            ("Points", [T("Sewer", "drop", tool("services_page", "arm", "pt_sewer")), T("Water", "drop", tool("services_page", "arm", "pt_water")),
                        T("Electrical", "bolt", tool("services_page", "arm", "pt_elec")), T("DB on house", "pin", tool("services_page", "arm", "port_db"))]),
            ("Plan", [T("PDF", "pdf", tool("services_page", "save_pdf"), hot=True), T("Image", "export", tool("services_page", "save_png"))])])
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
        st_ = getattr(self.win, "xa_steps", None)
        if st_ is not None and st_.reveal(gb):
            return
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
    hb.setSpacing(8)
    rail = Rail(win, make_icon, light_fn)
    right = QWidget()
    rv = QVBoxLayout(right)
    rv.setContentsMargins(0, 0, 0, 0)
    rv.setSpacing(8)
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
        lp = cur in (getattr(win, "launcher_idx", None) or ())
        ribbon.show_for(cur)
        ribbon.setVisible(not lp)
        ss = getattr(win, "step_strip", None)
        if ss is not None:
            ss.setVisible(not lp)
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
        rail.setVisible(win.width() >= 900 and not lp)

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
