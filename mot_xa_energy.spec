# PyInstaller spec - builds the folder dist/MCP_XA_Energy
from PyInstaller.utils.hooks import collect_all
datas, binaries, hidden = [("version.txt", "."), ("app_config.json", "."), ("mail_client.json", "."), ("RELEASE_NOTES.md", ".")], [], ["contacts", "mail_oauth", "mail_autoconfig", "register_ext", "mail_design", "contacts"]
for pkg in ("ifcopenshell", "rapidocr_onnxruntime", "onnxruntime", "shapely", "fitz", "pymupdf", "ezdxf", "matplotlib"):
    try:
        d, b, h = collect_all(pkg)
        skip = lambda t: any(x in str(t[0]).replace("\\", "/").split("/") + str(t[1]).replace("\\", "/").split("/") for x in ("tests", "sample_data", "testing"))
        d, b = [x for x in d if not skip(x)], [x for x in b if not skip(x)]
        h = [x for x in h if ".tests" not in x and ".testing" not in x]      # tests and sample data are never used by the program
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
a = Analysis(["mot_xa_energy.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=["tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MCP_XA_Energy", console=False, icon="mcp_logo.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="MCP_XA_Energy")
