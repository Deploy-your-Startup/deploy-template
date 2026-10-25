# 0004 — Separate cancellable verification from protected publication

## Context

Serializing a complete application workflow makes new pushes wait through old
tests and deployment. Cancelling the complete workflow instead can interrupt
deployment. Different services must not interleave publication across runs.

## Decision

Keep the public parallel workflow as an entry point. Call verification and
publication as separate reusable jobs. Only verification cancels an older run's
verification; publication holds a non-cancelling application/environment lock
around the entire service matrix. Check push freshness once inside that lock,
before any image publication. Preserve exact-source PR proof validation and
the full required-check gate. Do not increase the default E2E shard count.

## Consequences

New checks start without waiting for deployment. Already-started publication
finishes; stale push publication is skipped. Manual deployments can intentionally
select historical refs. Required-check paths acquire an additional `verify`
component, which consumers must account for in branch rules. GitHub scheduler
behaviour requires qualification on GitHub in addition to local integration
tests. See [deployment scheduling](../deployment-scheduling.md) for boundaries.
