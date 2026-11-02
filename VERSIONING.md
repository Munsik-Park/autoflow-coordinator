# Versioning

This repository's version is in the `VERSION` file at the root (Munsik-Park/autoflow-coordinator#14, operator decision 2026-10-31).

- **Format**: `<supported AutoFlow version>-rcN`. Example: `0.6.0-rc1`
- **Raising**: every PR that changes the coordinator raises rc by one in that PR.
- **Supporting a new AutoFlow version**: start again at `<new version>-rc1`.
- **Comparison**: `tools/prepare.py` stops without creating a run if `VERSION` without `-rcN` differs from the installed AutoFlow version. Work that adds support for a new AutoFlow version skips this comparison with `--skip-version-check` (Munsik-Park/autoflow-coordinator#18).
- **Tag**: tag the merge commit `v<version>`. Example: `v0.6.0-rc1`
