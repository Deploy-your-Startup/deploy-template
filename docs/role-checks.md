# Checking shared Ansible roles

Run the same checks locally and in CI:

```sh
mise run check
```

Global uv selects the interpreter committed in `.python-version`. The check
runtime is locked in `uv.lock`; no project or cloud credentials are needed.
`./make.sh lint` validates YAML, duplicate keys and misplaced task keywords.
`./make.sh test` loads every role and included task file through Ansible and
checks storage placement, teardown guards, secret censorship and Cloud-init
rendering. The restore integration test runs the actual playbook shell scripts
against a disposable Docker database using the role's pinned Postgres image,
with a Kubernetes boundary stand-in; it checks rows, role ownership and
password-free process arguments. Docker-backed checks skip when Docker is
unavailable. CI sets `STARTUP_REQUIRE_DOCKER_TESTS=1`, which turns a skip of the
container E2E and OS-upgrade node checks into a failure.
Set RESTORE_POSTGRES_IMAGE to another installed Postgres image for an
additional compatibility check. These checks do not provision infrastructure or
execute a deployment.

The KPI browser checks also need the pinned Chromium shell once:

```sh
uv sync --locked
uv run --locked playwright install --only-shell chromium
```

`./make.sh test` runs scenarios in parallel pytest-xdist workers against one
Docker daemon. Give every container, image tag and Compose project a unique
name, publish only on loopback ports Docker or the kernel just chose, and filter
Docker queries by your own names or labels, never by shared image IDs. Docker
adds an IPv6 address to the host side of each new container interface about two
seconds after start, and Chromium aborts in-flight requests on that change with
`ERR_NETWORK_CHANGED`. Browser checks therefore wait for those addresses before
starting and before repeating a step that Chromium aborted with that error, and
share one `xdist_group` so they do not start containers under each other. Run
one scenario serially with `uv run --locked pytest -n0 tests/<file>.py`.

The CLI also provides a syntax-only command:

```sh
startup ansible validate --playbook tests/roles.yml \
  --inventory tests/inventory.ini --roles-path roles
```

Use a static test inventory to avoid provider lookups. The command uses local
files without refreshing shared roles or resolving a Vault password.

## CI workflows of this repository

| Workflow | Runs |
| --- | --- |
| `check-roles.yml` | `./make.sh lint` and `./make.sh test` with Docker checks required |
| `check-pinned-runtime.yml` | the immutable runtime dispatch of the composite actions |
| `testing-policy.yml` | Markdown link and testing-policy documentation checks |

The behaviour these checks protect is described in
[operational safeguards](operational-safeguards.md). Release steps live in
[releasing](releasing.md).
