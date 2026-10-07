from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.auth.jwt_handler import create_access_token
from app.auth.auth_dependencies import get_current_user, require_admin
from app.auth.password_handler import hash_password, verify_password
from app.core.database import get_db
from app.models.user import User
from app.input.auth_schema import RegisterRequest, LoginRequest
from app.observability.audit_logger import audit_log

router = APIRouter()


@router.post("/register")
async def register(
    user_data: RegisterRequest,
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        User.email == user_data.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    hashed_password = hash_password(user_data.password)

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hashed_password
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    audit_log(
        action="USER_REGISTERED",
        user_id=str(new_user.id)
    )

    return {
        "message": "User registered successfully",
        "user_id": new_user.id,
        "username":new_user.username,
        "email": new_user.email
    }

@router.post("/login")
async def login(
    user_data: LoginRequest,
    db: Session = Depends(get_db)
):
    # Check for configured TEST login (when PostgreSQL DB is on remote/office laptop)
    if (
        getattr(settings, "enable_test_login", False)
        and getattr(settings, "test_user_email", None)
        and getattr(settings, "test_user_password", None)
        and user_data.email.strip().lower() == str(settings.test_user_email).strip().lower()
        and user_data.password == settings.test_user_password
    ):
        test_id = getattr(settings, "test_user_id", "test_user_123")
        test_role = getattr(settings, "test_user_role", "USER")
        access_token = create_access_token(test_id, test_role)
        audit_log(
            action="USER_TEST_LOGIN",
            user_id=test_id,
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
        }

    try:
        user = db.query(User).filter(
            User.email == user_data.email
        ).first()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. If running in test mode, enable test login.",
        ) from e

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    password_valid = verify_password(
        user_data.password,
        user.password_hash
    )

    if not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    access_token = create_access_token(
        str(user.id),
        user.role.value)

    audit_log(
        action="USER_LOGIN",
        user_id=str(user.id)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/test-token")
async def test_token():
    token = create_access_token("test_user_123","USER")

    return {
        "access_token": token,
        "token_type": "bearer"
    }


@router.get("/protected-test")
async def protected_test(current_user=Depends(get_current_user)):
    return {
        "message": "Authentication successful",
        "user_id": current_user["user_id"],
        "role": current_user["role"]
    }

@router.get("/admin-test")
async def admin_test(current_user=Depends(require_admin)):
    return {
        "message": "Admin access successful",
        "user_id": current_user["user_id"],
        "role": current_user["role"]
    }

@router.get("/me")
async def get_me(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        user_id = int(current_user["user_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authenticated user",
        )

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
    }