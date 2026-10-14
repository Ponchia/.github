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

```sh
python3 scripts/repository_policy.py --validate-policy
python3 scripts/repository_policy.py --all
python3 scripts/repository_policy.py --all --json
python3 scripts/repository_policy.py --repo Ponchia/bronto-layout
```

The tool does **not** modify anything by default.
It returns a nonzero exit code for a policy violation, unmanaged repository
or API error. Advisories and explicitly waived findings do not fail.

## Reviewed plan/apply workflow

Repository-setting changes now require a reviewed plan. Unplanned direct
--apply calls to repository_policy.py are deliberately refused.

1. Run scripts/governance_v2.py plan --all (or --repo Ponchia/example).
2. Inspect the generated private JSON plan: its audit evidence, proposed
   actions, preconditions, policy/code digests and 24-hour expiry.
3. Run scripts/governance_v2.py apply --plan PLAN_FILE --approve PLAN_SHA256
   using the full SHA-256 printed by the first command.
4. Inspect the verification receipt under
   ~/.local/state/ponchia-governance/receipts/.

The plan is unusable if its content, policy, implementation, public
repository inventory or any target's relevant GitHub settings or default
branch head has changed. Every target is re-checked before a write.
The authenticated identity must be Ponchia. A receipt is created before
mutation; each plan can be attempted only once. If an operation fails
partway, inspect the receipt and generate a new plan after reconciliation.
Never replay a receipt whose effects may be unknown.

The allowlist is intentionally narrow:

1. Enable vulnerability alerts (required for Dependabot security updates).
2. Enable Dependabot security updates when disabled.
3. Enable automatic removal of merged PR branches.
4. Enable the Sponsor button only if Ponchia's exact Ko-fi link resolves.
5. Only with no existing protection or effective rulesets, initialize
   branch protection: require PRs, admin enforcement, successful required
   checks, conversation resolution and no force pushes/deletions.

First-time branch protection verifies each explicitly named CI check is
currently successful on the default-branch head, and pins the GitHub app ID.
It never guesses checks or replaces existing protection rules.

Existing CI, branch protection, metadata, licenses, secrets, releases,
deployments, visibility and repository deletion are never changed
by this mechanism.

## Evidence and weekly monitoring

A read-only watch is installed on the authenticated devbox as a systemd
user timer (not a privileged public GitHub Actions workflow). Run:

```sh
bash scripts/install_governance_watch.sh
systemctl --user start ponchia-governance-watch.service
systemctl --user list-timers ponchia-governance-watch.timer
journalctl --user -u ponchia-governance-watch.service -n 50 --no-pager
```

The timer is scheduled every Monday at about 09:00 Europe/Madrid and
persists across missed runs on the devbox. The machine must be running
(or come back online) for scheduled checks to execute. Keep the existing
GitHub CLI login authorized.

Evidence is stored under ~/.local/state/ponchia-governance/ with restricted
permissions. Watch snapshots are individually SHA-256 identified and
retained for the most recent 40 runs. Approved change plans and
non-replayable receipts are stored separately; this is local evidence,
not a cryptographic signature or an external compliance service.

Only errors, policy drift, unregistered original repositories and recovery
from such findings affect the notification fingerprint. Advisory-only
differences, skipped forks and unchanged findings are silent.

When meaningful drift appears, the watch may create or update one issue
in Ponchia/.github. It resolves the issue when the audit becomes clean.
Issue writes do not change repository configuration. GitHub's delivery of
notifications about one's own issues is not guaranteed: check or
subscribe to the issue, or configure a separate external notification
channel. Failures remain visible in the systemd journal. A failed issue
write does not acknowledge the alert cursor and is retried next run.

To inspect without notifying:

```sh
python3 scripts/governance_v2.py watch --notify none
```

Normal GitHub Actions in this repository still test the code using only
contents:read. They do not hold account-level administration credentials.

## Registering new repositories

Add the repository to `policy/repositories.json`, select a profile and
provide the exact successful CI check names for maintained projects.
Review and merge the policy change as a normal PR, then audit again.
Do not invent required checks before the CI has executed.

## Documented exceptions

An example entry for an intentional deviation:

```json
{
  "profile": "project",
  "requiredChecks": ["ci-gate"],
  "waivers": {
    "branch.pull_request": "Reviewed exception for an explicitly documented release process"
  }
}
```

A waiver is always reported. It does not automatically weaken a setting.
Agents should supply concrete evidence for proposed changes and treat
a deviation as a question until its reason is understood.

## Ongoing use

Run the auditor after publishing a new project, when CI check names change,
and during periodic maintenance. The JSON report can feed an agent's review.
Keep monitoring separate from privileged mutations.

See [the publishing guide](PUBLISHING.md).
