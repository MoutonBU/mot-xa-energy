import os, sys, time, faulthandler
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(120, exit=True)
from PySide6.QtWidgets import QApplication, QMessageBox
import mot_xa_energy as M
M.save_settings=lambda:None
app=QApplication([])
w=M.MainWindow(); w.resize(1500,900); M.apply_glass_theme(app,w); w.show()
def pump(s):
    t=time.time()
    while time.time()-t<s: app.processEvents()
pump(0.8)
rp=w.register_page
import register_ext, register
LOGK=register_ext.LOGK
# 400 orders and 600 drawings must not freeze the program (every row used to get 5-7 widgets at once)
rp.companies[:]=[{"name":"Cosmo","emails":"","keys":"","rules":"","default_area":""}]
rp.areas[:]=[{"name":"Area %d"%i,"keys":"","codes":"","company":"Cosmo"} for i in range(30)]
for i in range(400):
    e={k:"" for k in LOGK}; e.update({"group":"House %d"%(i//3),"type":"Order","text":"Order %d"%i,"status":"Open","priority":"Normal","area":"Area %d"%(i%30),"company":"Cosmo"}); rp.log.append(e)
t=time.time(); rp.refresh_log(); dt=time.time()-t; assert dt < 3.0, dt
from PySide6.QtWidgets import QMessageBox
QMessageBox.question=staticmethod(lambda *a,**k: QMessageBox.StandardButton.No)
rp._company_dialog=lambda *a,**k:("Newco","","","","")
t=time.time(); rp.new_company(); dt=time.time()-t; assert dt < 2.0, dt
for i in range(600):
    rp.rows().append({"no":"A%03d"%i,"title":"D%d"%i,"rev":"A","size":"A1","status":"For information","by":"","on":True,"path":"","file":"x.pdf"})
t=time.time(); rp.refresh(); dt=time.time()-t; assert dt < 2.0, dt
rp.tab.scrollToBottom(); pump(0.3)
assert rp.tab.cellWidget(rp.tab.rowCount()-1, register.KEYS.index("status")) is not None     # rows get their drop-downs when scrolled into view
print("ok big lists")
