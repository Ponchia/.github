# Agent guidance for Ponchia/.github

This repository governs GitHub's fallback community files for the whole
Ponchia account. Review changes for their impact on other repositories,
including private repositories and forks.

- Do not put secrets, access tokens or private deployment details here.
- Keep default files concise. Project-specific instructions should remain in
  their own repositories and override these defaults.
- Treat sponsorship and repository-policy scripts as maintainer-controlled.
  Keep them read-only by default. The direct policy --apply mode is retired;
  use reviewed one-use plans and their full SHA-256 approval, owner checks,
  verified CI requirements, existing protections and fork exclusions.
- Do not attempt to create or alter other repositories automatically in CI.
- Python standard library + authenticated gh CLI; no additional runtime deps.
- Run: python3 scripts/repository_policy.py --validate-policy
- Run: python3 -m unittest discover -s tests -v
- Run: python3 -m compileall -q scripts tests
- Run: actionlint .github/workflows/*.yml (when installed).
- Changes to account-level defaults should explain likely downstream effects.

- Never schedule repository administration writes. The systemd watch may
  only audit repos and create/update its own drift issue when findings change.
- Keep the plan SHA, bounded expiry, source hashes, fresh state preconditions
  and one-use receipt boundary intact.
- Test notification deduplication and failure-retry behavior offline.
