# Changing shared roles and playbooks

Notes for contributors. Users follow [Usage in Your Projects](../README.md#usage-in-your-projects).

## How a change reaches a project

```
Deploy-your-Startup/deploy-template     source of truth
        │  startup sync                 copies it into the owner's account
        ▼
<github-owner>/deploy-your-startup      per-owner copy that projects clone
        │  startup ansible setup_ansible
        ▼
<project>/deployment/.shared-roles      gitignored working copy at the pinned ref
```

The owner is inferred from the project's own Git remote; the repository name is
fixed (`DEFAULT_SHARED_REPO_NAME` in the CLI). Merging here is only the first
hop: no project runs the change until the owner syncs and reviews its role pin.
The same applies to the shared workflows. Sync, pinning and release
verification are described in [releasing](releasing.md).

To test an unmerged role change against a real project, push the branch to the
owner copy and pass `--version <branch>`; `setup_ansible` fetches and checks out
any ref in that repository. The CLI refuses to treat a modified `.shared-roles`
checkout as up to date, so never hand-edit it.

## Shared playbooks cannot see project `group_vars`

`backup-`, `restore-`, `update-vms-` and `k3s-upgrade-` playbooks run from
`.shared-roles/`. Ansible resolves `group_vars/` relative to the playbook, and the
project's lives one level up in `deployment/`. A shared playbook may therefore
only use:

- variables the CLI passes with `--extra-vars`
- host facts and values read from the node itself
- role defaults

Referencing a vaulted project value such as `k3s_token` fails with
`'x' is undefined` at the task, possibly minutes into a run. When the node
already has the secret, read it there (see the k3s role's upgrade block). A role
that needs project settings cannot run from a shared playbook; the CLI runs the
project's own `playbook.yml` with tags instead, as `startup ansible
cert-manager-upgrade` does for `cert_manager_solver`.
