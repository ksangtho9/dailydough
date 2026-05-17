from __future__ import annotations
import json
import logging
import urllib.request
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwk, jwt
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import Profile
from app.user_schemas import UserOut
from app.core.config import settings
from app.core.rate_limiter import limiter

logger = logging.getLogger("bakezy.auth")

_supabase_public_key: Any = None


def _get_supabase_public_key() -> Any:
    global _supabase_public_key
    if _supabase_public_key is None:
        url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=10) as r:
            jwks = json.loads(r.read())
        _supabase_public_key = jwk.construct(jwks["keys"][0])
        logger.info("Loaded Supabase public key (ES256)")
    return _supabase_public_key


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Profile:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        public_key = _get_supabase_public_key()
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        user_id: str | None = payload.get("sub")
        email: str | None = payload.get("email")
        if user_id is None:
            raise credentials_exception
    except JWTError as e:
        logger.warning("JWT decode failed: %s", e)
        raise credentials_exception

    profile = db.query(Profile).filter(Profile.id == user_id).first()
    if profile is None:
        profile = Profile(id=user_id, email=email, is_admin=False)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


async def require_admin_user(
    current_user: Profile = Depends(get_current_user),
) -> Profile:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def set_user_state(
    request: Request,
    current_user: Profile = Depends(get_current_user),
) -> Profile:
    request.state.user = current_user
    return current_user


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: Profile = Depends(get_current_user)):
    return current_user
