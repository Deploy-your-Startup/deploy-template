# deploy-template contributor instructions

This repository supplies the shared foundation for Deploy Your Startup.
Read README.md and the existing workflows before changing it. Keep public
instructions self-contained, in concise English, with neutral sample names.
Users retain ownership of their code, accounts, servers and credentials.

## Tests and runtime

Every behavior change ships with integration tests, never unit tests. Exercise
real scripts, Git repositories, Copier renders or Ansible loading and assert
what the user sees. Replace only external boundaries that cannot run locally.
Use GIVEN / WHEN / THEN. Run mise run check.
Use global uv with the committed .python-version and run project commands
through mise. Formatting may write; lint must only check. Do not add git hooks.

## Release and operations

Check README, agent instructions, metadata, license and public version refs
together. Release only tested commits and pin consumer versions. Local checks
do not prove successful cloud provisioning or production deployment.
Use startup CLI for Vault, provisioning, deployment and shared-role sync.
Never log or commit real credentials. Secret values use stdin and Keychain;
preview changes with --dry-run. Ask before destructive or costly operations.

Keep application template updates (startup template update) separate from
shared deployment updates (startup sync). Preserve application customizations
and deployment/group_vars. Never hand-edit deployment/.shared-roles.
