# Releasing and pinning

Merging to `main` here changes no project. A change reaches an application only
after the owner syncs it and reviews the project's pin; see
[role distribution](role-distribution.md) for the path.

## Verification before release

After `mise run check`, exercise a fresh single-node project in an authorized
test account: first install, repeat infrastructure, application deployment, DNS
and HTTPS, backup and restore into a disposable database, then explicit
upgrades. Also verify private-node bootstrap with Tailscale and the ten-minute
join-key window. Review optional charts and provider settings separately.
Static checks do not establish successful provisioning or production readiness.

A feature that needs a CLI change is usable only once that CLI is released;
state the minimum CLI version in the change description.

## Syncing into the owner repository

```sh
startup sync --source-version <reviewed-revision> --dry-run
startup sync --source-version <reviewed-revision>
```

Sync copies this repository into `<github-owner>/deploy-your-startup`. It does
not update existing workflow references or role pins in projects. Do not
confuse it with `startup template update` (Copier), which updates application
templates.

## Pinning a project's roles

Resolve a reviewed owner-repository ref:

```sh
startup ansible pin --working-directory deployment --version <reviewed-ref>
```

Commit `shared-roles.ref` and `shared-roles.sha256` with the CLI dependency and
lock file. Subsequent runs use that immutable commit. CI exports must match the
checksum of role files and runtime configuration, even without Git metadata; a
mismatch fails before any role executes. The first Git-backed setup records the
resolved commit automatically. Advancing the owner repository's `main` alone
does not change a pinned project.

When `deployment/shared-roles.ref` exists, the `deploy` and
`export-shared-roles` actions dispatch to the action code at that exact commit.
Projects without a pin use the action's current revision. A runtime-equivalent
commit can change action code while leaving the role checksum unchanged, so
review the action diff too. Projects pinned before the standalone exporter
existed must move to a revision that contains it before relying on the
pre-deploy checksum check.

## Pinning workflow references

Point application workflows at a reviewed commit of the owner repository, not
`@main`:

```yaml
uses: <github-owner>/deploy-your-startup/.github/workflows/build-and-deploy-service-parallel.yml@<commit-sha>
```

In the parallel workflow, `pin-ci-runtime` loads the shared test, coverage,
build-evidence and browser actions from the same commit as the caller's
reference. The `deploy` and `export-shared-roles` actions follow the project's
`shared-roles.ref` when it exists. Other nested action references in the sequential
workflows still use the owner repository's `main`.

## Credentials in CI

The workflows take the caller's `VAULT_PASSWORD` secret and pass it to the CLI
as the scoped `STARTUP_VAULT_PASSWORD` environment variable. The CLI streams
the deploy key directly to `ssh-add`; no password enters a process argument.
