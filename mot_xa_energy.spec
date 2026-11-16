# PyInstaller spec - builds the folder dist/MCP_XA_Energy
from PyInstaller.utils.hooks import collect_all
datas, binaries, hidden = [("version.txt", "."), ("app_config.json", ".")], [], []
for pkg in ("ifcopenshell", "rapidocr_onnxruntime", "onnxruntime", "shapely", "fitz", "pymupdf"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
a = Analysis(["mot_xa_energy.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=["tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MCP_XA_Energy", console=False, icon="mcp_logo.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="MCP_XA_Energy")
