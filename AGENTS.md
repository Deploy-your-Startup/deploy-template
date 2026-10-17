# deploy-template contributor instructions

This repository supplies the shared deployment foundation for Deploy Your
Startup. Read README.md and the existing workflows before changing it; read
[Changing shared roles and playbooks](docs/role-distribution.md) before editing
roles, shared playbooks or workflows. Keep public instructions self-contained,
in concise English, with neutral sample names. Users retain ownership of their
code, accounts, servers and credentials.

## Tests

Follow [Testing policy and completion evidence](docs/testing-policy.md) and
[when E2E runs](docs/e2e-execution.md). Run `mise run check`. Use global uv with
the committed `.python-version`; formatting may write, lint only checks, and
there are no Git hooks.

## Release and operations

Check README, agent instructions, metadata, license and public version refs
together. Release only tested commits and pin consumer versions. Local checks do
not prove cloud provisioning or a production deployment.

Use the startup CLI for Vault, provisioning, deployment and shared-role sync.
Secret values use stdin and Keychain, previewed with `--dry-run`; never log or
commit credentials. Ask before destructive or costly operations. Application
template updates (`startup template update`) and shared deployment updates
(`startup sync`) stay separate; preserve application customizations and
`deployment/group_vars`.
