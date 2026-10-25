# 0005 — Run E2E locally or in CI

**Status:** Accepted

## Context

A complete local browser run can establish the changed user flows before
release. Repeating it automatically on every PR and push consumes hosted runner
minutes. Small owner-operated startups may prefer local verification, while
keeping the same test suite and the option to execute it in CI.

## Decision

Keep integration tests as the default and browser E2E for changed user flows.
Use the smallest scenario matrix that covers distinct behaviour. Do not repeat
presentation-only tests across unrelated configuration states or keep duplicate
scenarios. Preserve success, validation, permission and relevant browser checks.

The shared container E2E workflow reads one repository variable,
`STARTUP_E2E_MODE`:

- Unset or `ci`: execute E2E in CI, with every enabled shard required to pass.
- `local`: automatic runs omit browser image builds and tests. Before approving
  the change, the operator or coding agent must run the complete applicable
  E2E suite locally against the final committed source and record the commit,
  command, passed/failed/skipped results and relevant reports in the PR or work
  record. Subsequent relevant source changes require another local run.

Manual `workflow_dispatch` runs execute E2E in either mode. Existing
`run_e2e: true` callers keep the E2E workflow connected to their deployment gate;
the central workflow selects where execution happens. No new caller input,
project-specific CI logic, local-evidence service or cryptographic attestation
is introduced. Leave `run_e2e` enabled rather than permanently bypassing the
shared workflow. Invalid mode values fail the workflow.

Local mode is an explicit operator trust policy. CI cannot establish that the
local run happened. Its summary says E2E was not executed in CI and does not
report a local pass. Changes made by automation still need a local verification
before approval, or a manual CI run. Projects that cannot enforce this rule
should keep CI mode. Neither mode proves production deployment health.

Verified PR build evidence includes the selected execution mode. A record made
in local mode cannot suppress required E2E after switching to CI mode.

## Distribution

Shared workflow behaviour is maintained here and distributed by `startup sync`
plus reviewed caller pins. Application testing ADRs and policies refer to this
decision; distribute those references through the application templates and
`startup template update`. Existing deployments do not change modes just by
updating their documentation. Selecting local mode is a separate explicit
repository configuration choice.

## Consequences

Local mode saves hosted browser-runner minutes while retaining the test suite.
It relies on disciplined local execution and loses an independent CI replay.
Default CI mode remains appropriate for unattended dependency updates and
collaborative projects. One shard remains the cost-conscious default; additional
shards require a measured benefit in elapsed time and total runner minutes.
