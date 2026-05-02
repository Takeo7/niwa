# Online Publication

Niwa can publish two surfaces:

- `ui_domain`: the Niwa UI/API, for example `niwa.example.com`.
- `apps_domain`: wildcard project apps, for example `apps.example.com`, where
  each public project is routed as `<slug>.apps.example.com`.

Projects are private by default. A project is routed publicly only when
`public_enabled=true`.

## VPS Mode

1. Point DNS at the VPS:
   - `A niwa.example.com -> VPS_IP`
   - `A *.apps.example.com -> VPS_IP`
2. Enable auth before exposure:
   ```bash
   niwa-executor set-password
   niwa-executor doctor --strict
   ```
3. Render Caddy:
   ```bash
   niwa-executor proxy render \
     --ui-domain niwa.example.com \
     --apps-domain apps.example.com \
     --tls-email admin@example.com
   ```
4. Run or reload Caddy:
   ```bash
   caddy run --config ~/.niwa/caddy/Caddyfile
   caddy reload --config ~/.niwa/caddy/Caddyfile
   ```

## Home Or Tunnel Mode

Use the same rendered Caddyfile behind a tunnel provider or router port
forward. DNS still needs one UI hostname and one wildcard apps hostname.

For local TLS testing:

```bash
niwa-executor proxy render \
  --ui-domain niwa.local \
  --apps-domain apps.niwa.local \
  --local-tls
```

## Static Deployments

Static projects route through the backend:

```caddyfile
slug.apps.example.com {
  rewrite * /api/deploy/slug{uri}
  reverse_proxy localhost:8000
}
```

The backend serves the active deployment artifact when one exists, otherwise
it falls back to `<project.local_path>/dist`.

## Process Deployments

Process deployments route directly to the active local port:

```caddyfile
slug.apps.example.com {
  reverse_proxy localhost:41001
}
```

If there is no active port, the rendered route contains a comment instead of
guessing.

## Validation

Render without writing by using:

```bash
niwa-executor proxy render --print
```

Validate syntax when Caddy is installed:

```bash
niwa-executor proxy validate
```
