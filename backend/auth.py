"""
Microsoft Entra External ID bearer-token validation for the browser SPA (MSAL.js, PKCE).

The React SPA signs customers in through the EXTERNAL tenant (tst-customers) and gets an access
token for this API's scope (api://<ENTRA_CLIENT_ID>/access_as_user). It sends it as
`Authorization: Bearer <jwt>` on every call. Here we validate it: RS256 signature against the
tenant's signing keys, issuer, audience, expiry and scope.

The issuer and signing-key URL are read from the tenant's OpenID configuration rather than
hard-coded: an external tenant's issuer is GUID-based (https://<tenantId>.ciamlogin.com/<tenantId>/v2.0).

Not the same tenant as AZURE_TENANT_ID, which is the Default Directory used for Cosmos access (db.py).
"""
import json
import logging
import os
import threading
import urllib.request

import jwt  # PyJWT
from dotenv import load_dotenv
from jwt import PyJWKClient

# Local dev reads the project-root .env; in the container the variables come from the Container App.
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

log = logging.getLogger("auth")

SUBDOMAIN = os.getenv("ENTRA_TENANT_SUBDOMAIN", "")
TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
API_SCOPE = os.getenv("ENTRA_API_SCOPE") or f"api://{CLIENT_ID}/access_as_user"
SCOPE_NAME = API_SCOPE.rsplit("/", 1)[-1]

_LEEWAY = 60  # seconds of clock-skew tolerance on exp/nbf/iat


class AuthError(Exception):
    """Raised when a request isn't properly signed in. Carries the HTTP status to return."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _require_settings() -> None:
    missing = [name for name, value in (
        ("ENTRA_TENANT_SUBDOMAIN", SUBDOMAIN), ("ENTRA_TENANT_ID", TENANT_ID), ("ENTRA_CLIENT_ID", CLIENT_ID),
    ) if not value]
    if missing:
        raise RuntimeError(f"Missing {', '.join(missing)} (see docs/SETUP.md).")


def public_config() -> dict:
    """Non-secret settings the browser needs to start sign-in."""
    _require_settings()
    return {
        "clientId": CLIENT_ID,
        # Includes the tenant ID: MSAL v5 rejects the GUID-based issuer (endpoints_resolution_error)
        # when the authority is only https://<subdomain>.ciamlogin.com/.
        "authority": f"https://{SUBDOMAIN}.ciamlogin.com/{TENANT_ID}/",
        "scopes": [API_SCOPE],
    }


def is_real_email(value) -> bool:
    """Entra gives customer accounts an internal <guid>@<tenant>.onmicrosoft.com username; that isn't an email."""
    return isinstance(value, str) and "@" in value and not value.lower().endswith(".onmicrosoft.com")


# The OpenID metadata (issuer + signing-key client) is fetched once and cached. PyJWKClient caches the
# keys themselves and refetches when it sees an unknown key ID (key rotation).
_metadata = None
_metadata_lock = threading.Lock()


def _get_metadata() -> dict:
    global _metadata
    with _metadata_lock:
        if _metadata is None:
            url = f"https://{SUBDOMAIN}.ciamlogin.com/{TENANT_ID}/v2.0/.well-known/openid-configuration"
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 (fixed https URL)
                meta = json.load(resp)
            _metadata = {"issuer": meta["issuer"], "jwks": PyJWKClient(meta["jwks_uri"])}
        return _metadata


def authenticate(authorization: str | None) -> dict:
    """Validate the bearer token and return {id, email, name}. Raises AuthError."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "Not signed in.")
    token = authorization[7:].strip()
    _require_settings()

    try:
        meta = _get_metadata()
    except Exception as exc:  # network / DNS / bad tenant settings
        log.warning("OpenID metadata fetch failed: %s", exc)
        raise AuthError(503, "Sign-in service unavailable. Check ENTRA_TENANT_SUBDOMAIN and ENTRA_TENANT_ID.") from exc

    try:
        signing_key = meta["jwks"].get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=[CLIENT_ID, f"api://{CLIENT_ID}"],  # passes if ANY listed audience matches
            issuer=meta["issuer"],
            leeway=_LEEWAY,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        # Logged server-side only. Common causes: expired token, token version not 2.
        log.warning("Token rejected: %s: %s", type(exc).__name__, exc)
        raise AuthError(401, "Session expired or invalid. Please sign in again.") from exc

    scopes = claims.get("scp", "").split()
    if SCOPE_NAME not in scopes:
        log.warning("Token missing scope %s (has: %s)", SCOPE_NAME, claims.get("scp"))
        raise AuthError(403, "Token does not grant access to this API.")

    email = claims.get("email")
    return {
        "id": claims.get("oid") or claims.get("sub"),  # Entra object ID: the only stable key
        # Only the `email` optional claim. Never preferred_username, which can be the internal
        # <guid>@<tenant>.onmicrosoft.com name for customer accounts.
        "email": email if is_real_email(email) else None,
        "name": claims.get("name"),
    }
