# Bronto projects

Choose a project by the problem it solves. These libraries can be used
independently; adopting one does not require the others or a private application.
This directory is a manual guide, not an installer, shared release train or
GitHub-inherited community default.

## Visual libraries and testing

| Need | Project | Boundary |
| --- | --- | --- |
| Consistent HTML interfaces, themes and design tokens | [Bronto UI](https://github.com/Ponchia/bronto-ui) | Semantic CSS classes and optional JavaScript behaviors. The application owns its state and navigation. |
| Explanatory callouts over an existing chart, diagram or interface | [Bronto Annotations](https://github.com/Ponchia/bronto-annotations) | Headless note/connector placement and optional renderer adapters. The host supplies geometry and owns persistence and target identity. |
| Test approved relationships between measured elements | [Bronto Layout](https://github.com/Ponchia/bronto-layout) | Layout contracts and diagnostics, not a graph layout generator. Missing measurements are not a pass; geometry alone does not prove visual quality. |
| Identified, editable visual artifacts with purpose-built views | [Bronto Visual Models](https://github.com/Ponchia/bronto-visual-models) | Visual content semantics and renderer lifecycles. The host owns authorization, persistence, data access and navigation. |

Start with the project's README for its installation path, runnable example,
current limitations and supported environments. Source versions, release
archives and registry packages can differ, particularly during a beta. This
page deliberately does not keep a second version table.

These projects are complementary rather than one mandatory stack. UI can style
a page that uses no visualization library. Annotations explains a host's existing
content. Layout checks an explicitly reviewed relationship instead of approving
whatever arrangement it discovers. Visual Models retains family-specific
capabilities; one artifact need not translate into every renderer.

## Separate applications

[Bronto Pulse](https://github.com/Ponchia/bronto-pulse) tracks source-aware
software and website discovery, distribution and usage. Its README identifies
it as a public source preview. Collected analytics, credentials and deployments
remain private by default. Public source is not a hosted-service or production
readiness promise, and Pulse is not a dependency of the visual libraries.

## Integrate and contribute

Each repository owns its package exports, tests, licensing and release process.
Use its published installation instructions and keep the selected artifact in
the consumer's lockfile. A passing test against an upstream source checkout does
not prove that an older published archive contains the same fix. Qualify the
actual artifact through its public exports, without aliases into private source
or dependencies accidentally supplied by another checkout.

Keep application policy in the application. A reusable library should not need
the host's credentials, database schema or deployment configuration. A working
standalone example establishes that packaging is usable outside its original
host; independent user adoption requires separate evidence.

Report a problem in the repository that owns the behavior, with a minimal
reproduction, artifact version and host environment. For security reports,
follow that repository's security policy or its applicable support guidance;
do not post credentials or private datasets in an issue.

Project-specific documentation remains authoritative. This directory introduces
no compatibility policy across all projects, account-level configuration change,
automatic upgrade process or requirement to release them together.
