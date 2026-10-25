# 0005 — Local tests, optional CI E2E

**Status:** Accepted

Run lint and all tests locally before completing code changes. Read `run_e2e`
in the project workflow: `false` skips the additional CI browser run; `true`
enables it. Dependabot PRs always run E2E in CI.

Keep this rule in the shared workflow. No repository variable is needed.
