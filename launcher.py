"""Start-up file of the installed program.

When a code-only update has been installed (Menu > Check for updates), the newer .py files live in
~/MCP_XA_Energy/code_update and are used in place of the ones inside the installer. They are used only while they belong to the
installed program (meta.json "base" equals the installed version) and are newer than it. If they fail to load, they are put aside
(code_update.bad) and the program starts from the installer's own files."""
import importlib.abc
import importlib.util
import json
import os
import re
import sys


def _ver(txt):
    return tuple(int(x) for x in re.findall(r"\d+", str(txt)))


def _installed():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as f:
            return _ver(f.read())
    except Exception:
        return ()


class _Overlay(importlib.abc.MetaPathFinder):
    def __init__(self, folder):
        self.folder = folder

    def find_spec(self, name, path=None, target=None):
        if "." in name:
            return None
        f = os.path.join(self.folder, name + ".py")
        if os.path.isfile(f):
            return importlib.util.spec_from_file_location(name, f)
        return None


def overlay_folder():
    return os.path.join(os.path.expanduser("~"), "MCP_XA_Energy", "code_update")


def _start_overlay():
    d = overlay_folder()
    try:
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        inst = _installed()
        if not inst or _ver(meta.get("base")) != inst or _ver(meta.get("ver")) <= inst:
            return None
        finder = _Overlay(d)
        sys.meta_path.insert(0, finder)
        os.environ["MOT_CODE_VER"] = str(meta["ver"])
        os.environ["MOT_CODE_DIR"] = d
        return finder
    except Exception:
        return None


def _drop_overlay(finder):
    d = finder.folder
    try:
        sys.meta_path.remove(finder)
    except ValueError:
        pass
    for n, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if f and os.path.abspath(f).startswith(os.path.abspath(d)):
            del sys.modules[n]
    os.environ.pop("MOT_CODE_VER", None)
    os.environ.pop("MOT_CODE_DIR", None)
    try:
        bad = d + ".bad"
        if os.path.isdir(bad):
            import shutil
            shutil.rmtree(bad, ignore_errors=True)
        os.rename(d, bad)
    except Exception:
        pass


def run():
    finder = _start_overlay()
    try:
        import mot_xa_energy as M
    except Exception:
        if finder is None:
            raise
        _drop_overlay(finder)
        import mot_xa_energy as M
    if len(sys.argv) >= 4 and sys.argv[1] == "--plan-worker":
        import ifc_plan
        ifc_plan.worker_main(sys.argv[2], sys.argv[3])
        sys.exit(0)
    M.main()


if __name__ == "__main__":
    run()
