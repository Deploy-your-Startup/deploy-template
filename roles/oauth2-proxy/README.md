# oauth2-proxy

Deploy the pinned upstream image as shared infrastructure. There is no
application source, Dockerfile or build workflow. Updates reach consumers
through `startup sync` and a reviewed project shared-role pin.

Projects guard the role in their own playbook; the role does not define a toggle:

```yaml
- name: Deploy authentication proxy
  ansible.builtin.import_role:
    name: oauth2-proxy
  when: oauth2_proxy_enabled | default(false)
  tags: oauth2-proxy
```

The same guard works with `include_role`. `oauth_enabled` is the old
application-template name; the later template phase will rename it to
`oauth2_proxy_enabled`.

## Configuration

Set these variables in project `deployment/group_vars`:

| Variable | Required value |
| --- | --- |
| `oauth2_proxy_enabled` | `true` to include the role |
| `base_domain` | Public base domain, for example `example.com` |
| `auth_domain` | OIDC issuer URL without its trailing slash, for example `https://login.example.com` |
| `auth_audience` | Intended API audience, for example `https://example.com/private_api` |
| `oauth2_proxy_client_id` | OIDC application client ID, stored in Vault |
| `oauth2_proxy_client_secret` | OIDC application client secret, stored in Vault |
| `oauth2_proxy_cookie_secret` | Vault value: 16/24/32 raw bytes or URL-safe base64 decoding to that length |

For encoded cookie secrets use the RawURLEncoding alphabet (`A-Z`, `a-z`,
`0-9`, `-`, `_`); trailing `=` padding is accepted. The Kubernetes Secret
adds a separate base64 encoding. Credentials enter the pod through `envFrom`,
never command-line arguments. Secret application uses `no_log` and disables diff.

Defaults select `backend.example.com` for callbacks, `.example.com` for the
cookie and redirect whitelist, and `http://backend.<namespace>.svc.cluster.local:8000`
for the upstream. `k8s_namespace` defaults to `default` when absent. Override
`oauth2_proxy_host`, `oauth2_proxy_upstream`, `oauth2_proxy_cookie_domain`, and
`oauth2_proxy_whitelist_domain` for another topology, including an apex-only site.
Register `https://<oauth2_proxy_host>/oauth2/callback` with the OIDC provider.

`oauth2_proxy_version` pins the image (`v7.13.0`). The protected-route default
is `oauth2_proxy_skip_auth_route: "!=^/private_api"`; it must retain its leading
`!`. `oauth2_proxy_extra_skip_auth_routes` defaults to `["OPTIONS=^/private_api"]`.
`oauth2_proxy_extra_jwt_issuers` defaults to `{{ auth_domain }}/={{ auth_audience }}`;
the issuer's trailing slash matters because token issuers are compared literally.
There is no implicit audience fallback. `oauth2_proxy_extra_args` defaults to
`[]`; review overrides carefully because flags and extra skip routes can weaken
authentication. Do not put credentials in extra arguments.

## Routing and authentication

Use a streaming reverse proxy: ingress → oauth2-proxy → backend. Route
`/private_api` through the proxy, never directly to a backend that trusts its
Authorization header. The role deploys the proxy Service and Deployment;
the project owns ingress routing and backend CORS configuration.

Route `/oauth2/*` on the frontend origin to the same proxy, so browser session
requests are same-origin: the proxy's own endpoints do not supply CORS headers.
The API can use `backend.example.com`; the HttpOnly, secure cookie scoped to
`.example.com` reaches both the frontend and API subdomains. Only trusted
subdomains should share that cookie scope.

The negated skip route makes endpoints outside `/private_api` anonymous.
OPTIONS preflight requests under `/private_api` also skip authentication:
browsers send no credentials on preflight, and rejecting it prevents the real
request. The backend must return CORS headers and keep OPTIONS free of side
effects; subsequent writes still require authentication.

Browsers authenticate with a session cookie. `--pass-authorization-header=true`
supplies the upstream Authorization header for those requests. Native clients
can send bearer tokens: `--skip-jwt-bearer-tokens=true` verifies the issuer,
signature and audience before forwarding them without a browser login redirect.

Reverse proxying avoids ForwardAuth response-body buffering. Keep the 128Mi
memory limit and health probes; a regression should fail within the pod's limit
rather than exhaust the node. Project development and end-to-end tests should
use the real proxy with a mock OIDC provider and the same routing, preflight and
authentication flags.
