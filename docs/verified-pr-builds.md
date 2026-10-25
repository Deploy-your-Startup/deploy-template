# Reusing a verified PR build

The parallel service workflow can reuse production images from a successful
pull-request run after a push. It compares the tracked Git tree, complete caller
inputs, resolved service matrix, calling workflow identity and immutable shared
CI runtime revision. Squash, merge and equivalent direct-push commits can reuse
the same result even when their commit SHAs differ.

Direct pushes to the deployment branch remain supported. Branch protection and
an up-to-date-branch rule are not prerequisites. Without matching evidence the
normal build, configured integration/lint/coverage checks and enabled E2E suite
all run before publication. Required checks remains the deployment gate.

## Controls and compatibility

`reuse_pr_build` defaults to `true` in
`build-and-deploy-service.yml`. Set it to `false` to force fresh builds
and checks, including after a dependency or base-image security update. Manual
`workflow_dispatch` runs always execute fresh checks, regardless of this input.

Both Django and Vue application templates already call this build workflow;
there are no portfolio names, account-specific settings or per-project patches
in this mechanism. Cloudflare Pages workflows do not reuse PR evidence; their
existing checks remain unchanged.

The first PR after adoption runs in full and creates the evidence for its push.
An existing project must reference a shared revision containing this feature.
Run `startup sync --source-version <reviewed-revision> --dry-run`, review the
changes, then sync that revision into the owner's shared deployment repository.
Update the application's workflow reference to the resulting immutable commit
in that owner repository. Syncing does not update existing caller pins. Do not
confuse shared deployment sync with `startup template update` (Copier).

Jobs selecting or restoring evidence require `actions: read`, `contents: read`
and `pull-requests: read` to recover the merged PR associated with its commit. PR jobs
need no registry-write credentials or deployment secrets for reuse. The normal
post-gate publication job retains its existing registry/deployment permissions.

## Evidence and failure behavior

Each image job uploads an immutable OCI archive with one-day retention.
Only the successful required-checks job records the source, configuration and
the exact artifact IDs and SHA-256 digests for **every** service. A push accepts
that record only after the entire PR workflow has completed successfully.
The trusted loader pins shared test, coverage and browser actions to the same
commit as the reusable workflow, including callers that reference a moving ref.

Selection validates the source merge against GitHub's original base and head,
reconstructs its tree with Git, verifies the workflow/runtime identity, and checks
all referenced images. It does not trust an image tag or a JSON assertion alone.
Evidence expires after one day. Fork PRs, unknown runtime revisions, additional
build contexts, missing metadata and incomplete reruns are not reusable. They
keep the full pipeline. A lookup API failure also falls back to full checks.

The publish job revalidates the selected evidence and checks the downloaded ZIP
against GitHub's immutable artifact digest before passing the OCI archive to
the image transfer tool. It does not execute files from the PR archive. If an
artifact disappears, changes or fails verification **after** selection, the job
fails before registry login/publication; rerun manually for fresh checks. No
failed, cancelled or unexpectedly skipped fresh checks authorize deployment.

Images and checks must depend on tracked source and the declared workflow
inputs. Branch-name/commit-derived build behavior, mutable external build
contexts and fresh upstream dependency resolution are not represented by a Git
tree. Use fresh checks for those requirements. Build reuse deliberately retains
the previously checked image; it does not claim that upstream tags or external
services are unchanged. New validation requirements should advance the shared
workflow revision, which invalidates earlier evidence.

## Cost and verification

Reuse saves repeated builds and test setup, but adds artifact storage and image
transfer, with one-day retention. The prepare/gate/publish jobs still execute.
Measure representative rounded job minutes and storage before claiming savings.
Superseded PR runs are cancelled per workflow/ref/environment/service. Running
production workflows are not interrupted by a newer push.

`tests/test_verified_build_integration.py` exercises real Git histories, the
shipped selector, recorder, restore process and gate shell against a local HTTP
stand-in for GitHub. It covers successful reuse, direct pushes, mismatched
configuration, failed runs and corrupt/missing evidence. This is not evidence
of a successful hosted Actions rollout or a production deployment. Keep the
existing application's required browser scenarios enabled and verify the first
PR, matching push and direct push in a consumer before declaring adoption done.
