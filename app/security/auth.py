"""
JWT authentication dependency — validates Cognito tokens exactly the same way
as the Spring Boot services (same issuer, same JWK endpoint).
"""
from __future__ import annotations

import httpx
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from app.config import get_settings

bearer_scheme = HTTPBearer()


@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """Fetch Cognito public keys (cached for process lifetime; restart to rotate)."""
    settings = get_settings()
    resp = httpx.get(settings.cognito_jwk_set_uri, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _credentials_exception(detail: str = "Could not validate credentials"):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> dict:
    """
    Validates the Cognito JWT and returns the decoded claims dict.
    Raises 401 on any validation failure.

    Downstream routes extract:
        token["sub"]              → user UUID (Cognito sub)
        token["cognito:groups"]   → list of group memberships
        token["email"]            → user email
        token["custom:org_id"]    → org UUID (if set in Cognito attributes)
    """
    token_str = credentials.credentials
    settings = get_settings()

    try:
        jwks = _fetch_jwks()
        # Decode header first to pick the right key
        header = jwt.get_unverified_header(token_str)
        kid = header.get("kid")

        # Find matching key in JWKS
        public_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                public_key = key
                break

        if public_key is None:
            raise _credentials_exception("Token signing key not found")

        claims = jwt.decode(
            token_str,
            public_key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer_uri,
            options={"verify_aud": False},  # Cognito tokens may omit audience
        )
        return claims

    except ExpiredSignatureError:
        raise _credentials_exception("Token has expired")
    except JWTError as exc:
        raise _credentials_exception(f"Invalid token: {exc}")


# Type alias for cleaner route signatures
CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_org_id(current_user: CurrentUser) -> str:
    """
    Extracts org_id from the JWT custom attribute.
    The org-service sets `custom:org_id` on the Cognito user after onboarding.
    """
    org_id = current_user.get("custom:org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organisation associated with this account. Complete onboarding first.",
        )
    return org_id


OrgId = Annotated[str, Depends(get_org_id)]
