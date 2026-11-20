"""Decides how a release is built: prints 'code' when only program code changed since the previous release (a small zip of the .py files
is enough), otherwise 'full' (a new installer). Used by the build workflow.

Full when: any file other than .py / notes / sql changed, a .py file imports a library no file imported at the previous release
(the installer would not contain it), or the commit message contains [full]."""
import ast
import os
import re
import subprocess
import sys

CODE_OK = re.compile(r"^(.*\.py|RELEASE_NOTES\.md|RELEASE_NUMBER|README\.md|.*\.sql)$")


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def imports_of(src):
    out = set()
    try:
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                out.update(a.name.split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                out.add(n.module.split(".")[0])
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


def decide():
    if "[full]" in git("log", "-1", "--format=%B"):
        return "full", "commit asks for a full build"
    revs = [x for x in git("log", "--format=%H", "-n", "2", "--", "RELEASE_NUMBER").split() if x]
    if len(revs) < 2:
        return "full", "no earlier release"
    prev = revs[1]
    changed = [f for f in git("diff", "--name-only", prev, "HEAD").split("\n") if f.strip()]
    other = [f for f in changed if not CODE_OK.match(f)]
    if other:
        return "full", "changed: " + ", ".join(other[:5])
    old, _ = tree_imports(prev)
    new, local = tree_imports()
    added = sorted(x for x in new - old - local if x not in ("__future__",))
    if added:
        return "full", "new imports: " + ", ".join(added)
    return "code", "only program code changed"


if __name__ == "__main__":
    kind, why = decide()
    print(why, file=sys.stderr)
    print(kind)
