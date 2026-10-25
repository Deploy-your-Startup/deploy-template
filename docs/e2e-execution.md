# When E2E runs

Workflow configuration determines whether the complete E2E job starts. Test
configuration determines whether individual scenarios execute after it starts.
A skipped job or scenario is not evidence that its user flow works.

## Workflow triggers

The project's `.github/workflows/` files define events, branches and `paths`.
Regular application checks run on matching pull requests and pushes to `main`.
A feature-branch push without an open matching pull request does not start those
checks. A manual `workflow_dispatch` starts the selected workflow independently
of its path filters.

Changes to application code, E2E files, Docker build context or the application
workflow should match the build/check triggers. Root documentation outside those
paths normally runs documentation checks only. Documentation inside `backend/**`
or `frontend/**` still matches those application paths and can start E2E.
Template CI renders and checks generated applications on pull requests and main
pushes without application path filters, including documentation-only changes.
Project-specific conditions can also skip E2E, for example a scheduled release
poll that has not selected an application deployment.

## Enabling the deployment gate

In the shared parallel build workflow, `run_e2e` enables the browser gate;
`e2e_shards` chooses its shard count and `e2e_directory` locates the harness.
`run_e2e` defaults to false for compatibility. Generated parallel-build callers
explicitly enable it; inspect each project's caller rather than relying on the
default. Every enabled shard must succeed before new production images publish.
A failed, cancelled or unexpectedly skipped required E2E job blocks publication.
`RUN_E2E_IN_CI=false` skips CI browser tests; unset/`true` enables them.
Dependabot PRs always run E2E in CI. All tests must still run locally.
See [the testing decision](adr/0005-local-or-ci-e2e.md).
After a push, the parallel workflow may reuse the exact image and successful
checks from an equivalent PR run. Its verified source/configuration/runtime
record replaces a fresh E2E execution; a missing or invalid record runs the full
pipeline. Direct-to-main remains supported. Manual runs always check afresh.
See [verified PR builds](verified-pr-builds.md) for eligibility, expiry and the
`reuse_pr_build: false` escape hatch.
Cloudflare callers use the shared container E2E workflow directly and make their
deploy job depend on the browser job.

See the actual [parallel build workflow](../.github/workflows/build-and-deploy-service-parallel.yml)
and [container E2E workflow](../.github/workflows/container-e2e.yml).

## Deployment paths without a fresh E2E run

The separate shared `deploy.yml` and `deploy-infrastructure.yml` workflows do
not call E2E. Project callers may invoke them manually, and some invoke
`deploy.yml` on changes under `deployment/**`. Direct deployment through the
startup CLI is also a separate path. These operations do not establish a fresh
E2E pass; the parallel build gate must not be described as protecting every
possible deployment path. Configuration or role changes can affect user flows
and need appropriate checks and deployment verification.

See the [direct deploy workflow](../.github/workflows/deploy.yml) and
[infrastructure workflow](../.github/workflows/deploy-infrastructure.yml).

## Individual scenario skips

Playwright `test.skip(...)` can skip a scenario even when the E2E job runs.
Provider-specific checks may require credentials or an external environment.
Additional Auth0 checks, for example, can be opt-in and skip without
their declared credentials; routine login flows use a local OIDC provider.
Report these skips and remaining gaps separately from successful scenarios.
