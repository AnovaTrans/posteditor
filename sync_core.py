"""Mirror the shared engine into the LQA repo.

`core/mtpe/` is canonical HERE. The LQA tool imports the same code, so copy it
over whenever the engine changes:

    python sync_core.py ../lqa

The target's own app.py / requirements.txt / tests are left untouched.
"""
import os
import shutil
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core")


def sync(target_repo: str):
    dst = os.path.join(target_repo, "core")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    n = sum(len(f) for _, _, f in os.walk(dst))
    print(f"synced core/ -> {dst} ({n} files)")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "../lqa"
    if not os.path.isdir(target):
        sys.exit(f"target repo not found: {target}")
    sync(target)
