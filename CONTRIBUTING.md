# Contributing to Ponchia projects

These repositories are independent projects with different release and testing
requirements. Start with the README and any repository-specific contributing
guide; the project-specific instructions take precedence over this account-wide
fallback.

## Before proposing a change

- Check the project documentation and existing issues or pull requests.
- For bugs, describe the affected version, a minimal reproduction, the observed
  result, and what you expected. Include a sanitized log only when useful.
- For features or breaking changes, open a focused issue before investing in a
  large implementation.

## Pull requests

- Keep changes scoped and explain the motivation and compatibility impact.
- Include a test or reproducible verification for behavioral changes, and update
  documentation when the user-facing contract changes.
- Follow the project's own formatting, CI, security, and release instructions.
  Passing checks is a prerequisite, not a guarantee that a change will be merged.
- Never include credentials, real user data, private operational details, or
  unrelated generated artifacts. Use synthetic fixtures when testing.

The maintainers review contributions as time permits; there are no guaranteed
response times. Do not publish or tag a release on behalf of a project.

## Reporting vulnerabilities

Please **do not disclose vulnerabilities in public issues or pull requests**.
Use the repository's security policy and GitHub private vulnerability reporting
when available. See [support guidance](SUPPORT.md) for other questions.
