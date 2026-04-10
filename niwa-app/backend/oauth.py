"""OAuth 2.0 + PKCE authentication for Niwa."""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import urllib.error
import logging

log = logging.getLogger("niwa.oauth")

# ── OpenAI OAuth Configuration ──
OPENAI_OAUTH_CONFIG = {
    "authorize_url": "https://auth.openai.com/oauth/authorize",
    "token_url": "https://auth.openai.com/oauth/token",
    "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
    "scopes": "openid profile email offline_access",
}


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def generate_state():
    """Generate random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def build_auth_url(provider, redirect_uri, state, code_challenge):
    """Build the authorization URL for the given provider."""
    if provider == "openai":
        config = OPENAI_OAUTH_CONFIG
        params = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": config["scopes"],
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
        }
        return f"{config['authorize_url']}?{urllib.parse.urlencode(params)}"
    raise ValueError(f"Proveedor OAuth no soportado: {provider}")


def exchange_code_for_tokens(provider, code, code_verifier, redirect_uri):
    """Exchange authorization code for tokens."""
    if provider == "openai":
        config = OPENAI_OAUTH_CONFIG
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": config["client_id"],
            "code_verifier": code_verifier,
        }).encode()
        req = urllib.request.Request(config["token_url"], data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = json.loads(resp.read())
                access_token = token_data.get("access_token", "")
                refresh_token = token_data.get("refresh_token", "")
                id_token = token_data.get("id_token", "")

                claims = parse_jwt(access_token)
                expires_at = claims.get("exp", 0) if claims else 0

                id_claims = parse_jwt(id_token) if id_token else {}
                email = (id_claims or {}).get("email", "")

                auth_claims = (claims or {}).get("https://api.openai.com/auth", {})
                account_id = auth_claims.get("chatgpt_account_id", "")

                return {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "id_token": id_token,
                    "expires_at": expires_at,
                    "email": email,
                    "account_id": account_id,
                    "provider": "openai",
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            log.error("Token exchange failed: %s %s", e.code, body)
            return {"error": f"Error intercambiando código: HTTP {e.code} — {body}"}
        except Exception as e:
            log.error("Token exchange error: %s", e)
            return {"error": f"Error: {e}"}
    return {"error": f"Proveedor no soportado: {provider}"}


def refresh_access_token(provider, refresh_token):
    """Refresh an expired access token using the refresh token."""
    if provider == "openai":
        config = OPENAI_OAUTH_CONFIG
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config["client_id"],
        }).encode()
        req = urllib.request.Request(config["token_url"], data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = json.loads(resp.read())
                access_token = token_data.get("access_token", "")
                new_refresh = token_data.get("refresh_token", refresh_token)

                claims = parse_jwt(access_token)
                expires_at = claims.get("exp", 0) if claims else 0

                id_token = token_data.get("id_token", "")
                id_claims = parse_jwt(id_token) if id_token else {}
                email = (id_claims or {}).get("email", "")

                return {
                    "access_token": access_token,
                    "refresh_token": new_refresh,
                    "id_token": id_token,
                    "expires_at": expires_at,
                    "email": email,
                    "provider": "openai",
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            log.error("Token refresh failed: %s %s", e.code, body)
            return {"error": f"Error refrescando token: HTTP {e.code}"}
        except Exception as e:
            log.error("Token refresh error: %s", e)
            return {"error": f"Error: {e}"}
    return {"error": f"Proveedor no soportado: {provider}"}


def parse_jwt(token):
    """Parse JWT payload without verification (we trust the issuer)."""
    if not token or token.count(".") != 2:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def is_token_expired(expires_at, margin_seconds=300):
    """Check if a token is expired or will expire within margin_seconds."""
    if not expires_at:
        return True
    return time.time() + margin_seconds >= expires_at
