# PyInstaller spec - builds the folder dist/MCP_XA_Energy
from PyInstaller.utils.hooks import collect_all, collect_data_files
datas, binaries, hidden = [("version.txt", "."), ("sig_template.png", "."), ("sig_icon_phone.png", "."), ("sig_icon_mail.png", "."), ("sig_icon_web.png", "."), ("app_config.json", "."), ("mail_client.json", "."), ("RELEASE_NOTES.md", ".")], [], ["contacts", "mail_oauth", "mail_autoconfig", "register_ext", "mail_design", "contacts", "sig_banner", "ui_extras", "tool_base", "area_schedule", "site_lines", "site_import", "archicad_link", "council_pack", "guidelines", "doc_review", "fen_advisor", "fen_headroom"]
# matplotlib has its own PyInstaller hook; ezdxf only needs its data files. Collecting every submodule of them only slows the build.
try:
    datas += collect_data_files("ezdxf")
except Exception:
    pass
for pkg in ("ifcopenshell", "rapidocr_onnxruntime", "onnxruntime", "shapely", "fitz", "pymupdf"):
    try:
        d, b, h = collect_all(pkg)
        skip = lambda t: any(x in str(t[0]).replace("\\", "/").split("/") + str(t[1]).replace("\\", "/").split("/") for x in ("tests", "sample_data", "testing"))
        d, b = [x for x in d if not skip(x)], [x for x in b if not skip(x)]
        h = [x for x in h if ".tests" not in x and ".testing" not in x]      # tests and sample data are never used by the program
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
a = Analysis(["mot_xa_energy.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "IPython", "pytest", "sphinx", "PyQt5", "PyQt6"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MCP_XA_Energy", console=False, icon="mcp_logo.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="MCP_XA_Energy")
