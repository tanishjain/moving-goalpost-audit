# Rebuild and verify the release

## Public-package verification

The standalone package can verify every distributed file without private data or third-party packages:

```bash
python verify_release.py
```

This is an integrity check, not a regeneration of the human-coded evidence or model run.

## Maintainer rebuild from the private research archive

One deterministic entry point regenerates the package from the immutable internal inputs
(`data/validation/error_cascade.csv`, `gate_c_registry_timing.csv`, `g2_sampling_probabilities.csv`,
and the frozen G5 run `data/validation/g5/g5-reference-20260818-v1/`). It makes no model calls and
re-verifies the denominator invariant and hashes. The approved family is rebuilt and verified in private staging
by the family-aware package command, which also requires the private author-approval record. It builds the
complete display and release package twice, requires byte identity, runs the release audit and verifier, and
changes nothing active:

```bash
uv run --extra figures python scripts/validation/g3_final_package.py --family author_approved_post_audit --stage-only
```

`--promote` replaces the active `manuscript/assets/` and `release/` with the validated staged build. It is
reserved for an explicitly authorized activation and is not a verification or rebuild step. The release audit
accepts each supported presentation version of the approved family (the authenticated original signed release
and presentation-r2):

```bash
uv run python scripts/validation/audit_public_release.py release
```

The upstream G5 aggregate tables derive from the immutable run. The current G5 presentation revision r2
(corrected explanatory captions and the wrong-paper Arm-2 response aggregate; values unchanged) is preserved in
`data/validation/g5/g5_release_presentation_r2/`. Verify it by rebuilding into a fresh temporary directory and
comparing; the preserved directory is never rewritten:

```bash
G5_CHECK="$(mktemp -d)/g5_release_presentation_r2"
uv run python scripts/validation/g5_build_release.py --run-dir data/validation/g5/g5-reference-20260818-v1 \
    --out "$G5_CHECK"
diff -r "$G5_CHECK" data/validation/g5/g5_release_presentation_r2 && echo "G5 presentation r2 verified"
```

The historical 2026-08-18 release (presentation r1, superseded captions) is reproduced the same way:

```bash
G5_R1_CHECK="$(mktemp -d)/g5_release"
uv run python scripts/validation/g5_build_release.py --run-dir data/validation/g5/g5-reference-20260818-v1 \
    --presentation-revision r1 --out "$G5_R1_CHECK"
diff -r "$G5_R1_CHECK" data/validation/g5/g5_release && echo "G5 historical r1 verified"
```

The r2 directory was created once, on 2026-10-04, by the first command with
`--out data/validation/g5/g5_release_presentation_r2` while that directory did not yet exist. That one-time
creation is not a rebuild step: the builder refuses to write into any existing non-empty directory, including the
preserved r2 directory and the historical `data/validation/g5/g5_release/`.

Every artifact is hashed in `RELEASE_MANIFEST.json`; the two cascade denominator families
(P4-nested vs all-97) are in `cascade_denominators.csv` and asserted at build time.
