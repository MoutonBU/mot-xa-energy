"""Orders: the client's orders and changes, house by house, as a tool of its own on the start screen.

The orders and changes are kept with the drawing register (the same list goes into the register email and PDF), so this page shows the
register's own Orders and Client changes pages; nothing is copied."""
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class OrdersPage(QWidget):
    def __init__(self, host, register_page):
        super().__init__()
        self.host, self.reg = host, register_page
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.sub = QTabWidget()
        v.addWidget(self.sub)
        order_pg, change_pg = register_page.order_pages
        self.sub.addTab(order_pg, "Orders")
        self.sub.addTab(change_pg, "Client changes")
        register_page.orders_page = self
