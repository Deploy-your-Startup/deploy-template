# 0005 — Local tests, optional CI E2E

**Status:** Accepted

Run lint and all tests locally before completing code changes. Record failures
and skips.

`RUN_E2E_IN_CI=false` skips the additional CI browser run. Unset/`true` enables
it. Dependabot PRs always run E2E in CI. Keep this rule in the shared workflow.
