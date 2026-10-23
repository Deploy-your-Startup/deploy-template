# deploy-template contributor instructions

This repository supplies the shared deployment foundation for Deploy Your
Startup. Read README.md and the existing workflows before changing it; read
[Changing shared roles and playbooks](docs/role-distribution.md) before editing
roles, shared playbooks or workflows. Keep public instructions self-contained,
in concise English, with neutral sample names. Users retain ownership of their
code, accounts, servers and credentials. Record lasting design decisions as
ADRs in [docs/adr](docs/adr/README.md).

## Tests

Follow [Testing policy and completion evidence](docs/testing-policy.md) and
[when E2E runs](docs/e2e-execution.md). Run `mise run check`; see
[checking shared roles](docs/role-checks.md). Use global uv with the committed
`.python-version`. `./make.sh lint` only checks; this repository has no
formatter. There are no Git hooks.

## Pitfalls

- Shared playbooks run from `.shared-roles/` and cannot see project
  `group_vars`; see [role distribution](docs/role-distribution.md#shared-playbooks-cannot-see-project-group_vars).
- `hetzner-server` creates servers with `force: true`, so a `server_type` that
  differs from the real server would stop it to resize it. Keep the preflight
  guard and `allow_server_resize: false`; never weaken a teardown or resize
  guard to make a run pass.
- Merging here changes no project. Changes reach projects only through
  `startup sync` and a reviewed pin; see [releasing](docs/releasing.md).

## Release and operations

Check README, agent instructions, metadata, license and public version refs
together. Release only tested commits and pin consumer versions. Local checks do
not prove cloud provisioning or a production deployment.

Use the startup CLI for Vault, provisioning, deployment and shared-role sync.
Secret values go into Ansible Vault through stdin, previewed with `--dry-run`;
only the Vault password itself lives in Keychain or the CI secret. Never log or
commit credentials. Ask before destructive or costly operations. Application
template updates (`startup template update`) and shared deployment updates
(`startup sync`) stay separate; preserve application customizations and
`deployment/group_vars`.
