# Niwa Deployment Runbook

Last updated: 2026-05-01

This runbook covers production deployment of Niwa, including TLS, public exposure, and tunnel modes (NET-06/07/08).

## Prerequisites

- Linux host with `systemd --user` (or macOS with `launchctl`)
- Python 3.12, Node.js 22
- `gh` CLI installed and authenticated
- A domain you control (for VPS mode) **or** Cloudflare/Tailscale account (for tunnel mode)
- Caddy 2.x installed

## Local-only mode (default)

```bash
./bootstrap.sh
niwa-executor dev start
```

UI on http://127.0.0.1:5173, backend on http://127.0.0.1:8000. No auth, no TLS, no public access. Suitable for single-user laptop use.

## VPS mode (public access)

### 1. Configure base domain

Edit `~/.niwa/config.toml`:

```toml
[network]
base_domain = "niwa.example.com"
public_scheme = "https"
```

This auto-derives `ui_domain = "niwa.niwa.example.com"` and `apps_domain = "apps.niwa.example.com"`. Override individually if needed.

### 2. Enable auth

```bash
niwa-executor set-password
```

This creates `~/.niwa/auth/password.hash` and enables auth on all routes.

### 3. Generate Caddyfile

```bash
niwa-executor proxy render --tls-email admin@example.com
niwa-executor proxy validate --tls-email admin@example.com
```

Caddy file lands at `~/.niwa/caddy/Caddyfile`. Caddy must be configured to read from there.

### 4. Run Caddy with the generated config

```bash
caddy run --config ~/.niwa/caddy/Caddyfile
```

Caddy automatically obtains Let's Encrypt certificates for `tls_email`. DNS A records for `ui_domain` and `*.apps_domain` must point to the VPS public IP.

### 5. Reload after project changes

When you add/remove a project or change deploy state, regenerate the Caddyfile and reload Caddy:

```bash
caddy reload --config ~/.niwa/caddy/Caddyfile
```

A future PR will hook this into the project create/delete flow automatically.

## Tunnel mode (Cloudflare / Tailscale)

For users without public IPs or who prefer not to expose ports.

### Cloudflare Tunnel

```bash
cloudflared tunnel create niwa
cloudflared tunnel route dns niwa niwa.example.com
cloudflared tunnel --url http://127.0.0.1:8000 run niwa
```

Cloudflare handles TLS; backend stays bound to localhost. Skip the Caddy step.

### Tailscale Funnel

```bash
tailscale funnel 8000
```

Exposes the backend on `https://<tsname>.<tsnet>.ts.net` with auto-TLS. No DNS or cert management.

## Smoke check

```bash
curl -k https://niwa.example.com/api/health
# {"status":"ok","version":"..."}

curl -k https://niwa.example.com/api/auth/status
# {"enabled":true}
```

## Rollback

If a deployment misbehaves, the backend tracks all versioned deployments under `~/.niwa/deployments/{slug}/{id}/`. Use the UI's Deploys tab to roll back to a previous build.

## Hardening checklist

See `docs/SECURITY.md` for the full checklist. Key items:

- [ ] `chmod 700 ~/.niwa`
- [ ] Auth enabled (`niwa-executor set-password`)
- [ ] MCP tokens use minimal scopes (not `admin`)
- [ ] Caddy serving with TLS (or tunnel with auto-TLS)
- [ ] No project in `autonomy_mode = "dangerous"` unless you understand it
- [ ] Periodic `niwa-executor cleanup` (cron)
