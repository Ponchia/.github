# Publishing a new Ponchia repository

This is an owner checklist, not a universal application scaffold.
The goal is to publish focused, maintainable projects without drifting
configuration or making promises about support that cannot be kept.

## 1. Decide whether to publish

Keep experiments private until a public README can explain the project,
current maturity, installation and known limits. Do not expose secrets,
real credentials, proprietary code or internal deployment details.

For a public project, provide a real repository-local license. GitHub
cannot inherit a license through the account's `.github` defaults.

## 2. Prepare project-owned details

- README: purpose, requirements, installation, usage and maturity.
- LICENSE: appropriate to the project; no inherited default.
- SECURITY.md: realistic private reporting instructions, with supported
  versions if that distinction matters.
- CONTRIBUTING.md and issue templates: relevant to the project.
- CI: format, tests, builds and security checks appropriate to the stack.
- Dependabot: ecosystems actually used, with sensible update frequency.
- Branch protection: protect main and require the checks that make sense.
- About section: short description, homepage (if applicable) and topics.

Use project-specific community files when the central defaults are too generic.
In particular, do not rely on the central SUPPORT.md in place of a careful
SECURITY.md for a project that handles credentials or other sensitive data.

## 3. Publish and enable sponsorship

Create the repository through the GitHub UI or GitHub CLI, then push the code.
When the repository is public and you intend to maintain it:

```sh
gh auth status
python3 scripts/sponsorships.py Ponchia/new-project
python3 scripts/sponsorships.py Ponchia/new-project --apply
```

Run those Python commands from a clone of `Ponchia/.github`. The first call
audits; the second only changes the Sponsorships enabled flag after confirming
the Ko-fi link, and checks the final state. The central default should supply
the funding link if the new repository has no project-local FUNDING.yml.

Verify the public repository page shows the Sponsor button, and verify the
funding destination opens the correct Ko-fi account. A successful GraphQL
status is useful evidence but not a payment-flow test.

## 4. Register repository policy

For a newly published original project, add its `project` profile and
real successful CI check names to
[the policy](../policy/repositories.json), through a PR to `Ponchia/.github`.
Unregistered projects are reported but never automatically changed.

~~~sh
python3 scripts/repository_policy.py --repo Ponchia/new-project
python3 scripts/repository_policy.py --repo Ponchia/new-project --apply
~~~

See [the governance guide](REPOSITORY_POLICY.md). The policy tool
does not edit existing CI definitions or branch-protection rules.

## 5. Periodic account audit


```sh
python3 scripts/sponsorships.py --all --json
python3 scripts/repository_policy.py --all --json
```

Use the JSON output as input to a local agent or report if wanted. Do not
schedule a GitHub Actions job that tries to administer other repositories
using its standard GITHUB_TOKEN: it generally does not have account-wide
administration permission. The intended execution environment is a trusted,
authenticated maintainer machine.

## Scope and limits

- **Forks:** intentionally skipped by the onboarding command. GitHub can
  still inherit shared fallback files for a fork with no local equivalent.
  For a retained fork, preserve upstream funding and leave Sponsorships
  disabled unless there is a deliberate maintainer-specific reason.
- **Private repositories:** intentionally skipped; the account-wide default
  files may still be available to GitHub there.
- **Archived repositories:** left unchanged.
- **Overrides:** local community files win over central defaults.
- **Automation:** the sponsorship script only enables Sponsor buttons; the
  separate policy CLI has its own opt-in administration operations. Neither
  rewrites project CI, release processes, licenses or sources.
- **Security:** do not put tokens into scripts or logs. Use the already
  authenticated GitHub CLI rather than creating a broad long-lived PAT.

Later, if multiple independent repositories genuinely need the same new
workflow, consider a small pinned reusable workflow. Central defaults and
reusable workflows solve different problems, and should not be confused.
