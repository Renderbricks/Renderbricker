"""Vendor the Physicalbricks library into the add-on (system Python, UPDATES #59).

Usage:
  python scripts/core/vendor_physicalbricks.py [--repo <Renderbricks repo>] [--commit <rev>] [--check]

Copies physicalbricks/blender/physicalbricks of one commit of the Renderbricks repository - `git archive`, so only
tracked files - into addon/renderbricker/physicalbricks and writes SOURCE beside its VERSION: three lines
`version <VERSION>`, `revision <REVISION>`, `commit <40 hex>`. The folder is never edited by hand; a refresh is a
new run of this script on a Physicalbricks release (the maintainer's word).

--repo    default: the folder 260925_Renderbricks beside the main checkout of this repository (found through git, so
          a worktree of it finds the same one)
--commit  default: main
--check   writes nothing; compares every vendored file byte for byte with the archive of the commit named in SOURCE
          and prints VENDOR CHECK PASS, or the differing names and exits 1
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(ROOT, "addon", "renderbricker", "physicalbricks")
LIBRARY = "physicalbricks/blender/physicalbricks"
SKIP_DIRS = {"__pycache__"}
SKIP_ENDINGS = (".pyc", ".blend1")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True).stdout


def default_repo():
    """The library's repository beside the main checkout of this one (a worktree has its own folder elsewhere)."""
    common = git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(common))), "260925_Renderbricks")


def archive(repo, commit):
    """{relative path: bytes} of the library in that commit."""
    data = git(repo, "archive", "--format=tar", f"{commit}:{LIBRARY}")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name] = tar.extractfile(member).read()
    return files


def on_disk():
    """{relative path: bytes} of the vendored folder, build leftovers left out."""
    files = {}
    for dirpath, dirs, names in os.walk(TARGET):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name.endswith(SKIP_ENDINGS):
                continue
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                files[os.path.relpath(full, TARGET).replace(os.sep, "/")] = f.read()
    return files


def source_text(files, commit):
    version = files["VERSION"].decode().strip()
    revision = files["REVISION"].decode().strip()
    return version, revision, f"version {version}\nrevision {revision}\ncommit {commit}\n"


def vendor(repo, rev):
    commit = git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").decode().strip()
    files = archive(repo, commit)
    version, revision, text = source_text(files, commit)
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    for name, data in files.items():
        path = os.path.join(TARGET, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    with open(os.path.join(TARGET, "SOURCE"), "wb") as f:
        f.write(text.encode())
    print(f"VENDORED {version} revision {revision} {commit}")


def check(repo):
    try:
        with open(os.path.join(TARGET, "SOURCE"), "rb") as f:
            lines = f.read().decode().splitlines()
        commit = lines[2].split()[1]
    except (OSError, IndexError):
        print("VENDOR CHECK FAIL: no readable SOURCE in", TARGET)
        return 1
    want = archive(repo, commit)
    want["SOURCE"] = source_text(want, commit)[2].encode()
    have = on_disk()
    bad = sorted(n for n in set(want) | set(have) if want.get(n) != have.get(n))
    if bad:
        print("VENDOR CHECK FAIL:", ", ".join(bad))
        return 1
    print("VENDOR CHECK PASS", commit, f"{len(have)} files")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--commit", default="main")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo) if a.repo else default_repo()
    if a.check:
        return check(repo)
    vendor(repo, a.commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
