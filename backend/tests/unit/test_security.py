from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip():
    password_hash = hash_password("secret123")

    assert verify_password("secret123", password_hash)
    assert not verify_password("wrong", password_hash)


def test_jwt_roundtrip():
    token = create_access_token(subject="user-1")

    assert decode_access_token(token)["sub"] == "user-1"
