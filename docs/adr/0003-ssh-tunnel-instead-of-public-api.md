# 0003: Kubernetes API behind SSH

## Status

Accepted

## Context

An allowlist for port 6443 breaks whenever an operator's address changes, and a
public Kubernetes API is an unnecessary attack surface. Hosted GitHub runners
have no fixed addresses but must deploy over SSH.

## Decision

The firewall closes the Kubernetes API by default
(`firewall_api_source_ips: []`). `startup ansible kubeconfig` configures a
kubeconfig credential helper that opens an SSH tunnel on demand. SSH stays
public for hosted runners; private network mode moves SSH and the API onto a
tailnet instead.

## Consequences

- Fixing a client timeout never means reopening 6443; repair the tunnel.
- Every operator needs working, non-interactive SSH access to the master.
- Projects with fixed runners should restrict `firewall_ssh_source_ips`.
