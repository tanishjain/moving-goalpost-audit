#!/usr/bin/env python3
"""Integrity verification of this snapshot against EXPORT_MANIFEST.json (Python 3.11+, standard library only).

Checks that every listed file exists with the recorded SHA-256 and that no unlisted file is present. This is
an integrity check only; `reproduce/reproduce_analyses.py` is the separate analysis reproduction.

    python verify_snapshot.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Local working directories that a user's own runs may create; never part of the distributed snapshot.
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".venv", "reproduction_output"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path = HERE) -> list[str]:
    root = Path(root)
    manifest = json.loads((root / "EXPORT_MANIFEST.json").read_text())
    listed = manifest["files"]
    present = {p.relative_to(root).as_posix() for p in root.rglob("*")
               if p.is_file() and p.relative_to(root).parts[0] != ".git"
               and not (set(p.relative_to(root).parts) & IGNORED_DIRS)}
    problems = []
    for rel in sorted(set(listed) - present):
        problems.append(f"missing: {rel}")
    for rel in sorted(present - set(listed) - {"EXPORT_MANIFEST.json"}):
        problems.append(f"unlisted file: {rel}")
    for rel in sorted(set(listed) & present):
        if sha256(root / rel) != listed[rel]["sha256"]:
            problems.append(f"hash mismatch: {rel}")
    return problems


def main() -> int:
    problems = verify()
    if problems:
        print("snapshot verification FAILED:\n- " + "\n- ".join(problems))
        return 1
    n = len(json.loads((HERE / "EXPORT_MANIFEST.json").read_text())["files"])
    print(f"snapshot verified: {n} files match EXPORT_MANIFEST.json; no unlisted files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
