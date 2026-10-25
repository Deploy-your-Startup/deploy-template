# Architecture decision records

Each record states one lasting decision: context, decision and consequences.
Records 0001–0099 belong to this shared template; projects number their own
records from 0100. Supersede a record with a new one instead of rewriting it.

| ADR | Decision |
| --- | --- |
| [0001](0001-owner-copy-and-pinned-roles.md) | Projects consume shared roles through an owner copy and an immutable pin |
| [0002](0002-reuse-verified-pr-builds.md) | Pushes may reuse a verified, equivalent PR build |
| [0003](0003-ssh-tunnel-instead-of-public-api.md) | The Kubernetes API is closed; access goes through SSH |
| [0004](0004-separate-verification-and-publication.md) | Cancel obsolete verification while protecting application publication |
| [0005](0005-local-or-ci-e2e.md) | Select local or CI browser verification without changing the test suite |
