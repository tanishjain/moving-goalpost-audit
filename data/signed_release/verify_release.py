#!/usr/bin/env python3
"""Verify the curated release against its deterministic manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "RELEASE_MANIFEST.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    expected = manifest["release_artifact_sha256"]
    actual_files = {
        str(path.relative_to(HERE))
        for path in HERE.rglob("*")
        if path.is_file() and path.name != MANIFEST.name
    }
    missing = sorted(set(expected) - actual_files)
    extra = sorted(actual_files - set(expected))
    mismatched = sorted(
        name for name in set(expected) & actual_files if sha256(HERE / name) != expected[name]
    )
    if missing or extra or mismatched:
        raise SystemExit(
            f"release verification failed: missing={missing}, extra={extra}, mismatched={mismatched}"
        )
    print(f"release verified: {len(expected)} artifacts match RELEASE_MANIFEST.json")


if __name__ == "__main__":
    main()
