# Deployment scheduling

The parallel service workflow separates cancellable verification from protected
publication. Callers keep the existing workflow path and inputs; the default
E2E shard count stays at one. This reduces obsolete work without weakening the
integration, lint, coverage or enabled E2E gates.

## Automatic runs

Verification has a concurrency group per caller workflow, ref, environment and
application (`service`). A newer automatic run replaces older verification.
Each run still checks its own immutable source or verifies equivalent PR proof.
A changed source tree or configuration requires full checks; scheduling does not
make an outdated PR build eligible for reuse.

Publication starts only after successful verification. One non-cancelling lock
per application and environment covers all services together, across caller
workflows and refs. Use a stable application `service` identifier when multiple
callers target the same application. GitHub keeps one pending publication in
this group; a newer arrival replaces that pending job. Ordering is not assumed.

Inside the lock, a freshness check compares the current push's run number with
pushes to the same caller workflow and branch. It skips obsolete publication,
including an older workflow rerun that finishes later. It compares workflow
runs rather than branch HEAD, so documentation pushes excluded by caller path
filters do not suppress an otherwise valid deployment. An API error or missing
history fails closed. A newer push suppresses old publication even if the newer
checks fail: fix the new push or explicitly redeploy manually.

Once this check authorizes publication, the whole service matrix finishes under
the lock. A push arriving afterwards may begin verification, but cannot cancel
that publication. Deployment failure can still leave a partially updated
application; the lock does not provide transactional multi-service rollback.

## Manual runs and other deployment paths

Each manual verification has its own group. Manual runs always check afresh and
may deliberately deploy a historical ref. They share the application publication
lock, but bypass automatic freshness selection. A pending manual publication can
be replaced by another arrival, just like any pending job in that group.

The separate direct-deploy and infrastructure workflows, startup CLI operations,
caller-level concurrency settings and explicit human cancellations are outside
this scheduling boundary. A caller-level cancellation policy can still cancel a
running deployment; remove such a policy before relying on protected publication.

## Adoption and measurement

Release and sync the tested shared revision, then advance caller workflow pins
through review. No application changes merely by merging this repository.
If branch protection names the old `Required checks` path, update it for the
new `verify / Required checks` nesting before requiring the new revision.

Local integration checks exercise real freshness commands against an HTTP
GitHub boundary, proof reuse/fallback, and the actual gate scripts. GitHub's
hosted scheduler is not executed locally. Qualify a disposable consumer on
GitHub before production adoption: two successive pushes must cancel obsolete
verification; another push during publication must let publication finish; a
delayed older run must skip publication; and failed E2E must still block every
service. Include verified PR reuse and manual historical redeployment.

Compare commit-to-deployment elapsed time, summed runner minutes and actual
billable usage before and after adoption. More E2E shards are optional and
should not be enabled as part of scheduling changes without measurements.
