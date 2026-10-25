# 0006 — One service build workflow

**Status:** Accepted

`build-and-deploy-service.yml` is the only service build workflow. It carries
the verification/publication split, container E2E and verified PR builds; the
older single-job sequential implementation is gone.

`build-and-deploy-service-parallel.yml` stays as a deprecated alias that
forwards every input and the Vault secret, so references pinned to that name
keep working after `startup sync`. `pin-ci-runtime` and `verified-build`
identify the run by the entry point's name, which both direct and alias callers
reference. Remove the alias once no project points at it.
