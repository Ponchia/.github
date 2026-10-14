# Ponchia · GitHub defaults

A small collection of **fallback GitHub community files** and a deliberate
sponsorship-onboarding command for repositories owned by
[**Ponchia**](https://github.com/Ponchia).

This repository is not a monorepo, a project template, or a shared CI runner.
Each project owns its release process, tests, license, security policy and
technical contribution guidelines.

## What GitHub automatically provides

| File | Effect when a repository has no local equivalent |
| --- | --- |
| [`.github/FUNDING.yml`](.github/FUNDING.yml) | Fallback Ko-fi destination: [ponchia](https://ko-fi.com/ponchia) |
| [`SUPPORT.md`](SUPPORT.md) | Guidance for user questions and private security reporting |
| [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) | Short PR description and validation prompts |

GitHub prefers a repository's own files over these defaults. The files are
**not copied into other repositories**, and changing them does not modify
other repositories' Git histories.

**Important:** GitHub may use the shared defaults for any repositories owned
by Ponchia, including forks and private repositories. The default funding
destination is account-wide; it is not filtered by our onboarding command.
Funding links and the *Sponsorships enabled* repository setting are separate:
a funding link alone need not make the Sponsor button visible.

## Audit and enable sponsorship

Requires Python 3.10+ and GitHub CLI authenticated as Ponchia with permission
to update repository settings. All commands below are deliberately scoped to
this GitHub username.

Read-only audit of the public account:

```sh
python3 scripts/sponsorships.py --all
```

Enable missing Sponsor buttons where **Ko-fi is already resolved and verified**:

```sh
python3 scripts/sponsorships.py --all --apply
```

Onboard one newly published repository:

```sh
python3 scripts/sponsorships.py Ponchia/new-project --apply
```

For AI agents, machine-readable output is available:

```sh
python3 scripts/sponsorships.py --all --json
```

The command:
- **Does nothing by default**; `--apply` explicitly opts into mutation.
- Skips forks, archived and private repositories and this `.github` repository.
- Never edits source files, funding files, workflows or branch rules.
- Only enables Sponsorships after GitHub confirms
  `https://ko-fi.com/ponchia` as a funding link.
- Reads the repository again after each change to verify the resulting state.
- Exits with a nonzero status if an eligible repository needs attention.

If a new repository's default funding link has not propagated yet, the command
reports `missing_funding` rather than enabling an incomplete Sponsor button.
Re-run the audit later; do not add unnecessary duplicate files just to silence
the check.

## What stays project-specific

GitHub does **not** inherit CI workflows, Dependabot configuration,
branch protection, codeowner policy or licenses from this repository.
Those belong with each project's language, risk profile and lifecycle.
Existing `FUNDING.yml`, security policies and issue templates in individual
repositories continue to take precedence.

See [the publishing checklist](docs/PUBLISHING.md) for the complete workflow.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

Tests use a fake GitHub client: they cannot change repository settings.
The [CI workflow](.github/workflows/validate.yml) runs these tests on PRs.

MIT licensed. Changes to account-wide defaults should be reviewed for
their effect on *all* Ponchia repositories, not just this one.
