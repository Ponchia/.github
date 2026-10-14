# Agent guidance for Ponchia/.github

This repository governs GitHub's fallback community files for the whole
Ponchia account. Review changes for their impact on other repositories,
including private repositories and forks.

- Do not put secrets, access tokens or private deployment details here.
- Keep default files concise. Project-specific instructions should remain in
  their own repositories and override these defaults.
- Treat the sponsorship script as a maintainer-controlled tool. Read-only by
  default; never remove the --apply guard or fork/private/archived exclusions.
- Do not attempt to create or alter other repositories automatically in CI.
- Python standard library + authenticated gh CLI; no additional runtime deps.
- Run: python3 -m unittest discover -s tests -v
- Run: python3 -m compileall -q scripts tests
- Run: actionlint .github/workflows/*.yml (when installed).
- Changes to account-level defaults should explain likely downstream effects.
