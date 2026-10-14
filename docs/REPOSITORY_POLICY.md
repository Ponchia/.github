# Ponchia repository policy

This repository holds **desired GitHub settings**, not the source code or CI
of other projects. The goal is deliberate onboarding and explainable drift
detection rather than uniform settings for every repo.

## Structure

- [Repository policy](../policy/repositories.json): profiles and expectations.
- [Governance CLI](../scripts/repository_policy.py): live checks using the
  authenticated GitHub CLI and a per-repository structured report.
- Profiles: `project` (maintained OSS), `shared-defaults` (this repository)
  and `profile` (the profile README repository).
- New original repositories are reported as `unmanaged` until reviewed.
- Forks, private and archived repositories are not mutated.
- A reasoned `waivers` entry documents intentional exceptions rather than
  hiding differences.

## Read-only audit

Run these from a clone of `Ponchia/.github`:

~~~sh
python3 scripts/repository_policy.py --validate-policy
python3 scripts/repository_policy.py --all
python3 scripts/repository_policy.py --all --json
python3 scripts/repository_policy.py --repo Ponchia/bronto-layout
~~~

The tool does **not** modify anything by default.
It returns a nonzero exit code for a policy violation, unmanaged repository
or API error. Advisories and explicitly waived findings do not fail.

## Explicit, limited changes

~~~sh
python3 scripts/repository_policy.py --repo Ponchia/new-project --apply
python3 scripts/repository_policy.py --all --apply --confirm-owner Ponchia
~~~

The mutation allowlist is intentionally small:

1. Enable GitHub vulnerability alerts, the prerequisite for Dependabot fixes.
2. Enable Dependabot security updates, when currently disabled.
3. Enable automatic deletion of merged pull-request branches.
4. Enable the Sponsor button after checking Ponchia's exact Ko-fi link.
5. **Only in an otherwise unprotected branch with no effective ruleset**:
   establish PR-only changes, enforce admins, require the explicitly listed
   checks, resolve PR conversations, prohibit force pushes and branch deletions.

For the last operation, every listed check must have **completed successfully**
on the current default branch. The command pins its GitHub Actions app ID and
refuses setup if a check is missing, ambiguous, skipped or failed. Check names
are never inferred.

It verifies the resulting setting after each write and refuses to act if
repository ownership, visibility, branch name or existing rules cannot be
confirmed.

**Not automated:** editing existing protection rules, rewriting workflows,
setting licenses, modifying documentation, changing visibility, managing
secrets, altering deployments, changing metadata or deleting repositories.
These remain independent, project-specific decisions.

Do not put a privileged account credential into GitHub Actions to run
this script. Execute from a trusted, authenticated maintainer machine.

## Registering new repositories

Add the repository to `policy/repositories.json`, select a profile and
provide the exact successful CI check names for maintained projects.
Review and merge the policy change as a normal PR, then audit again.
Do not invent required checks before the CI has executed.

## Documented exceptions

An example entry for an intentional deviation:

~~~json
{
  "profile": "project",
  "requiredChecks": ["ci-gate"],
  "waivers": {
    "branch.pull_request": "Reviewed exception for an explicitly documented release process"
  }
}
~~~

A waiver is always reported. It does not automatically weaken a setting.
Agents should supply concrete evidence for proposed changes and treat
a deviation as a question until its reason is understood.

## Ongoing use

Run the auditor after publishing a new project, when CI check names change,
and during periodic maintenance. The JSON report can feed an agent's review.
Keep monitoring separate from privileged mutations.

See [the publishing guide](PUBLISHING.md).
