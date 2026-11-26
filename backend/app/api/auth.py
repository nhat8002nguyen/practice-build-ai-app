import asyncio

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DatabaseSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import User
from app.schemas.api import AuthRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(payload: AuthRequest, session: DatabaseSession) -> TokenResponse:
    existing_user = await session.scalar(
        select(User).where(User.email == payload.email)
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    encoded_password = await asyncio.to_thread(hash_password, payload.password)
    user = User(email=payload.email, password_hash=encoded_password)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from None
    await session.refresh(user)

    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=TokenResponse)
async def login(payload: AuthRequest, session: DatabaseSession) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == payload.email))
    password_matches = user is not None and await asyncio.to_thread(
        verify_password,
        payload.password,
        user.password_hash,
    )
    if not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=create_access_token(str(user.id)))
