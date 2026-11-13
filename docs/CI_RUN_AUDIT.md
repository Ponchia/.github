# Reviewing GitHub Actions execution volume

Use the read-only inventory before changing workflows to save CI resources.
The first useful signal is **workflow runs by event and workflow**, not the
number of checks visible on a pull request or the number of billable minutes.

From the authenticated maintainer shell, with Python 3.10+ and GitHub CLI:

    python3 scripts/actions_efficiency.py --start 2026-11-01 --end 2026-11-13
    python3 scripts/actions_efficiency.py --start 2026-11-01 --end 2026-11-13 --repo bronto-annotations --json

The utility reads only repositories already declared in policy/repositories.json.
It pages the entire requested interval and fails instead of reporting partial
counts if a page is missing or the total changes. Each workflow run counts once,
regardless of matrix jobs. Repeated PR/workflow attempts are separate, **not**
classified as waste: each source revision rightly requires new qualification.

GitHub's Actions API often omits pull request numbers from its run records,
even when the event is pull_request. The report counts those as
unboundPrRuns, not as successfully attributed PRs. To retain useful evidence
without guessing, sourceBranchAttempts groups only pull-request events by the
exact head repository, head branch and workflow. sameHeadCommitAttempts is a
narrower grouping that also requires an exact 40-character source commit SHA.
A branch can be reused or receive many legitimate commits; a same-commit run
may be a justified recheck or retry. Neither is an established duplicate or
an estimate of saved minutes. unknownSourceBranchRuns disclose the number of
runs that cannot safely be attributed to a head branch.

Inspect repeated jobs and setup before modifying workflows:

- Identify in-flight PR runs superseded by newer commits to the same PR.
- Identify overlapping PR/push triggers and repeated installs.
- Classify browser, security and publisher work by changed paths only if
  the classifier fails closed and all required checks still report correctly.
- Verify that changes to concurrency do not cancel independent main, scheduled
  or release verification.

Preserve branch protection and all release/security/browser acceptance checks.
Never remove a check merely to reduce run counts. Run counts are not elapsed
time, jobs or billable minutes; obtain job timings and account billing before
claiming measured savings.
