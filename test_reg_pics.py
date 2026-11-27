import os, sys, time, faulthandler
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(120, exit=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtCore import QMimeData, QBuffer, QIODevice
import mot_xa_energy as M
M.save_settings=lambda:None
app=QApplication([])
w=M.MainWindow(); w.resize(1500,900); M.apply_glass_theme(app,w); w.show()
t=time.time()
while time.time()-t<0.8: app.processEvents()
rp=w.register_page
import register_ext
assert hasattr(rp,"mail_strip") and rp.mail_pics==[]
img=QImage(300,200,QImage.Format.Format_ARGB32); img.fill(QColor("red"))
got=[]
register_ext.MarkupDialog.exec=lambda self: 0
rp.mail.picture.connect(lambda i: got.append(i))
md=QMimeData(); md.setImageData(img)
assert rp.mail.canInsertFromMimeData(md)
rp.mail.insertFromMimeData(md)
assert len(got)==1 and not got[0].isNull(), got
before=rp.mail.toPlainText()
assert rp.mail.toPlainText()==before
# picture list -> designed html with cid and related parts
from email.message import EmailMessage
m=EmailMessage(); m.set_content("hi")
rp.mail_pics.append({"bytes":b"\x89PNG\r\n\x1a\n"+b"0"*20,"ext":"png","caption":"Query"})
m.add_alternative(rp.design_html("Subj","Body text",both=True,pics=register_ext.pic_srcs(rp.mail_pics)),subtype="html")
register_ext.attach_pics(m,rp.mail_pics)
raw=bytes(m)
assert b"cid:mcppic0" in raw and b"Content-ID: <mcppic0>" in raw
rp.mail_strip.refresh()
print("ok reg pics")
