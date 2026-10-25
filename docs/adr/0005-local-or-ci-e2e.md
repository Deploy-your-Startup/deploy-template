# 0005 — Local tests, optional CI E2E

**Status:** Accepted

Run lint and all tests locally before completing code changes, including
integration, existing unit and browser E2E tests. Record failures and skips.

To save runner minutes, `STARTUP_E2E_MODE=local` omits browser E2E in automatic
CI runs. Unset/`ci` runs E2E in CI. Dependabot PRs and manual workflow runs always
execute CI E2E. CI does not verify local execution.

Keep this selection in the shared workflow, with `run_e2e` enabled in callers.
Use focused scenarios and avoid duplicate test matrices.
