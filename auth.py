# JWT Authentication Module for ReplenMobile Backend
# Verifies Supabase JWT tokens and extracts user identity

import os
import logging
from typing import Optional
from fastapi import HTTPException, Header

logger = logging.getLogger(__name__)

# Supabase JWT secret for token verification
_jwt_secret: Optional[str] = None


def _get_jwt_secret() -> str:
    """Get the Supabase JWT secret, cached after first call."""
    global _jwt_secret
    if _jwt_secret is None:
        _jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")
    return _jwt_secret


async def verify_jwt(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency that verifies the Supabase JWT token
    from the Authorization header and returns the user_id (sub claim).

    Usage:
        @app.post("/api/protected")
        async def protected_endpoint(user_id: str = Depends(verify_jwt)):
            ...

    Raises:
        HTTPException 401 if token is missing or invalid.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="認証が必要です",  # "Authentication required"
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="無効な認証ヘッダー形式です",  # "Invalid auth header format"
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    jwt_secret = _get_jwt_secret()

    if not jwt_secret:
        logger.error("SUPABASE_JWT_SECRET is not configured")
        raise HTTPException(
            status_code=500,
            detail="サーバー認証設定エラー",  # "Server auth config error"
        )

    try:
        from jose import jwt as jose_jwt, JWTError

        payload = jose_jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={
                "verify_aud": False,  # Supabase tokens may not always have aud
            },
        )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="トークンにユーザー情報がありません",  # "No user info in token"
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user_id

    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="無効または期限切れのトークンです",  # "Invalid or expired token"
            headers={"WWW-Authenticate": "Bearer"},
        )
    except ImportError:
        logger.error("python-jose is not installed")
        raise HTTPException(
            status_code=500,
            detail="サーバー認証設定エラー",
        )
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}")
        raise HTTPException(
            status_code=401,
            detail="認証に失敗しました",  # "Authentication failed"
            headers={"WWW-Authenticate": "Bearer"},
        )
