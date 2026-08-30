"""Mirror the shared engine into the sibling tool repos.

`core/mtpe/` is canonical HERE. The LQA and QA tools import the same code, so copy
it over whenever the engine changes:

    python sync_core.py            # syncs ../lqa and ../qa (whichever exist)
    python sync_core.py ../lqa     # or a specific target

The target's own app.py / requirements.txt / tests are left untouched.
"""
import os
import shutil
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core")
DEFAULT_TARGETS = ["../lqa", "../qa"]


def sync(target_repo: str):
    dst = os.path.join(target_repo, "core")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    n = sum(len(f) for _, _, f in os.walk(dst))
    print(f"synced core/ -> {dst} ({n} files)")


if __name__ == "__main__":
    targets = sys.argv[1:] or DEFAULT_TARGETS
    done = 0
    for t in targets:
        if os.path.isdir(t):
            sync(t); done += 1
        elif len(sys.argv) > 1:
            sys.exit(f"target repo not found: {t}")
        else:
            print(f"skip (not found): {t}")
    if not done:
        sys.exit("no target repos found")
