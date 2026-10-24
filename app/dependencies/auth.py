from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client

from app.database import get_supabase_admin, get_supabase_for_user

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    email: str | None
    access_token: str


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Validate the Supabase access token sent as `Authorization: Bearer <jwt>`."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return verify_access_token(credentials.credentials)


def verify_access_token(token: str) -> CurrentUser:
    """Check a Supabase access token with Supabase Auth. Blocking: call via a threadpool from async code."""
    try:
        response = get_supabase_admin().auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    if response is None or response.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    return CurrentUser(id=response.user.id, email=response.user.email, access_token=token)


def get_user_db(user: CurrentUser = Depends(get_current_user)) -> Client:
    """Supabase client scoped to the caller, so RLS policies apply."""
    return get_supabase_for_user(user.access_token)
