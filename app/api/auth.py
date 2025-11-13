from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database.database import get_db, Base, engine
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, Token, UserRead

# Ensure tables exist (simple bootstrap for demo)
Base.metadata.create_all(bind=engine)

router = APIRouter()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT config (for demo; consider moving to settings/env)
SECRET_KEY = "CHANGE_ME_IN_PRODUCTION"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def verify_password(plain_password: str, hashed_password: str) -> bool:
	return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
	return pwd_context.hash(password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
	if expires_delta is None:
		expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
	expire = datetime.now(timezone.utc) + expires_delta
	to_encode = {"sub": subject, "exp": expire}
	return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
	existing = db.query(User).filter(User.email == user_in.email).first()
	if existing:
		raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
	user = User(
		email=user_in.email,
		hashed_password=get_password_hash(user_in.password),
	)
	db.add(user)
	db.commit()
	db.refresh(user)
	return user


@router.post("/login", response_model=Token)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
	user: Optional[User] = db.query(User).filter(User.email == credentials.email).first()
	if not user or not verify_password(credentials.password, user.hashed_password):
		raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
	access_token = create_access_token(subject=str(user.id))
	return {"access_token": access_token, "token_type": "bearer"}


