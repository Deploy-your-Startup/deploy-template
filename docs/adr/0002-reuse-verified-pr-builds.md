# 0002: Reuse verified PR builds on push

## Status

Accepted

## Context

A merged pull request used to rebuild every image and rerun the full
integration and browser suites on `main`, although the tree had already passed
them. Direct pushes to `main` must stay possible, and branch protection is not
a prerequisite for portfolio repositories.

## Decision

The parallel service workflow records, after its required-checks gate, the Git
tree, caller inputs, service matrix, workflow identity, shared runtime revision
and the digests of every image archive. A push accepts that record only when it
reconstructs the same tree and identity and verifies every artifact digest.
Anything else runs the full pipeline. `reuse_pr_build: false` and manual runs
always check afresh.

## Consequences

- Equivalent merge, squash and direct-push commits deploy the already checked
  image without rebuilding it.
- Builds that depend on branch names, mutable external contexts or fresh
  upstream resolution must disable reuse.
- Evidence expires after one day and adds artifact storage; changing validation
  requirements advances the runtime revision and invalidates earlier evidence.
