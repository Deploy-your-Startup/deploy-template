# 0001: Owner copy and pinned shared roles

## Status

Accepted

## Context

Every startup deploys with the same Ansible roles and GitHub workflows. Users
own their repositories, servers and credentials, and a shared change must never
alter a running production deployment without the owner noticing. Projects also
run in CI without access to the upstream source repository.

## Decision

`startup sync` copies this repository into one private
`<github-owner>/deploy-your-startup` repository per owner. Projects resolve
roles and workflows only from that copy. Each project records the reviewed
commit in `deployment/shared-roles.ref` and its content checksum in
`deployment/shared-roles.sha256`; the CLI and the CI actions refuse a mismatch.

## Consequences

- Merging here changes no project; rollout needs a sync and a reviewed pin.
- Owners can customize their copy and test branches with `--version <branch>`.
- Shared playbooks run from `.shared-roles/` and cannot read project
  `group_vars`; they rely on CLI extra-vars, node facts and role defaults.
- Several owner copies may lag behind; release notes must state the minimum
  CLI version a change needs.
