from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.token_validator import validate_access_token


security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    try:
        return validate_access_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


def require_admin(
    current_user=Depends(get_current_user)
):
    if current_user["role"] != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    return current_user