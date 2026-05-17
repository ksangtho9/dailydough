from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models import User
from app.user_schemas import UserCreate, UserOut, Token
from app.core.config import settings
from app.core.rate_limiter import limiter


# ---- CONFIG ----
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

# Fail fast if using default secret in production-like environments
if SECRET_KEY == "CHANGE_ME_TO_A_LONG_RANDOM_STRING_DEV_ONLY":
    import warnings
    warnings.warn(
        "JWT_SECRET_KEY not set! Using insecure default. "
        "Set JWT_SECRET_KEY environment variable in production.",
        UserWarning
    )

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# IMPORTANT: this is where FastAPI gets the token from
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# 🔥 THIS is the thing router.py is trying to import
router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)



# ---------- Utility functions ----------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception

    return user


async def require_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency that requires the current user to be an admin.
    
    Always checks the database user record (never trusts JWT claims).
    Raises 403 Forbidden if user is not an admin.
    
    Returns the User object (guaranteed to be admin).
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def set_user_state(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency that sets request.state.user for rate limiting.
    
    This ensures authenticated endpoints populate request.state.user
    so the rate limit key function can use user-based keys.
    """
    request.state.user = current_user
    return current_user


# ---------- Routes ----------

@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    # Check if email already exists
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash password
    hashed_pw = get_password_hash(user_in.password)

    # Create user WITHOUT full_name
    user = User(
        email=user_in.email,
        hashed_password=hashed_pw,
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/token", response_model=Token)
@limiter.limit("5/minute")  # Rate limit: 5 requests per minute per IP
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
