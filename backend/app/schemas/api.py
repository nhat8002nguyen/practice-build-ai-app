from pydantic import BaseModel, Field, field_validator


class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("invalid email address")
        return normalized


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
