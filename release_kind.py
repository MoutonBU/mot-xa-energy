"""Decides how a release is built: prints 'code' when only program code changed since the previous release (a small zip of the .py files
is enough), otherwise 'full' (a new installer). Used by the build workflow.

Full when: any file other than .py / notes / sql changed, a .py file imports a library no file imported at the previous release
(the installer would not contain it), or the commit message contains [full]."""
import ast
import os
import re
import subprocess
import sys

CODE_OK = re.compile(r"^(.*\.py|RELEASE_NOTES\.md|RELEASE_NUMBER|FULL_BASE|README\.md|.*\.sql)$")


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def imports_of(src):
    """Full dotted names of the modules imported (os.path, html.parser...). A frozen program only contains the modules it imported when it was built."""
    out = set()
    std = getattr(sys, "stdlib_module_names", set())
    try:
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                out.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                out.add(n.module)
                if n.module.split(".")[0] in std:
                    out.update(n.module + "." + a.name for a in n.names)      # from email import policy
    except SyntaxError:
        pass
    return out


def tree_imports(rev=None):
    names = [f for f in (git("ls-tree", "-r", "--name-only", rev).split("\n") if rev else git("ls-files").split("\n")) if f.endswith(".py")]
    s = set()
    for f in names:
        src = git("show", "%s:%s" % (rev, f)) if rev else open(f, encoding="utf-8", errors="replace").read()
        s |= imports_of(src)
    return s, {os.path.splitext(os.path.basename(f))[0] for f in names}


def non_code(a, b):
    return [f for f in git("diff", "--name-only", a, b).split("\n") if f.strip() and not CODE_OK.match(f)]


def decide():
    if "[full]" in git("log", "-1", "--format=%B"):
        return "full", "commit asks for a full build"
    revs = [x for x in git("log", "--format=%H", "--", "RELEASE_NUMBER").split() if x]
    if len(revs) < 2:
        return "full", "no earlier release"
    # the last release that was a full installer: the one code updates are measured against
    base = revs[-1]
    for k in range(1, len(revs) - 1):
        if non_code(revs[k + 1], revs[k]) or "[full]" in git("log", "-1", "--format=%B", revs[k]):
            base = revs[k]
            break
    try:                                                      # FULL_BASE: the commit of the last installer that really was built (cancelled builds do not count)
        fb = open("FULL_BASE").read().strip()
        if fb and git("cat-file", "-t", fb).strip() == "commit":
            base = fb
    except OSError:
        pass
    other = non_code(base, "HEAD")
    if other:
        return "full", "changed: " + ", ".join(other[:5])
    old, _ = tree_imports(base)
    new, local = tree_imports()
    added = sorted(x for x in new - old if x.split(".")[0] not in local and x != "__future__")
    if added:
        return "full", "new imports since the last installer: " + ", ".join(added[:8])
    return "code", "only program code changed"


if __name__ == "__main__":
    kind, why = decide()
    print(why, file=sys.stderr)
    print(kind)
