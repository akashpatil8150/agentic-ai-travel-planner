from jose import JWTError, jwt
from app.core.config import settings


def validate_access_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        user_id = payload.get("sub")

        if not user_id:
            raise ValueError("Token does not contain user ID")

        return {
        "user_id": user_id,
        "role": payload.get("role")
        }

    except JWTError:
        raise ValueError("Invalid or expired token")