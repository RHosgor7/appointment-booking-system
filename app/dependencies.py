from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from app.auth import decode_token
from app.db import get_db
import aiomysql
from typing import Optional, Literal

security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    # Token yok/bozuk kontrolü
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing or invalid"
        )
    
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    # sub ve business_id zorunlu
    user_id_str = payload.get("sub")
    token_business_id_str = payload.get("business_id")
    
    if user_id_str is None or token_business_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # sub değerini int'e dönüştür
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token"
        )
    
    # business_id değerini int'e dönüştür
    try:
        token_business_id = int(token_business_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid business ID in token"
        )
    
    # Pool init kontrolü
    try:
        db_pool = await get_db()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    # DB'den user bilgisini çek (password_hash hariç, business_id ile birlikte kontrol)
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, email, full_name, role, created_at, updated_at FROM users WHERE id = %s AND business_id = %s LIMIT 1",
                (user_id, token_business_id)
            )
            user = await cursor.fetchone()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or unauthorized"
                )
            
            # Staff rolü için staff_id bilgisini ekle
            if user["role"] == "staff":
                await cursor.execute(
                    "SELECT id FROM staff WHERE user_id = %s AND business_id = %s LIMIT 1",
                    (user_id, token_business_id)
                )
                staff = await cursor.fetchone()
                if staff:
                    user["staff_id"] = staff["id"]
                else:
                    # Staff rolünde ama staff kaydı yok - bu durumda staff_id None
                    user["staff_id"] = None
            else:
                user["staff_id"] = None
            
            return user

# Authorization helper functions
def require_role(
    current_user: dict,
    allowed_roles: list[str],
    error_message: str = "Forbidden"
) -> dict:
    """Check if current user has one of the allowed roles"""
    if current_user.get("role") not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_message
        )
    return current_user

def require_owner_or_admin(current_user: dict) -> dict:
    """Require owner or admin role"""
    return require_role(
        current_user,
        ["owner", "admin"],
        "Only owner or admin can access this resource"
    )

def require_owner(current_user: dict) -> dict:
    """Require owner role"""
    return require_role(
        current_user,
        ["owner"],
        "Only owner can access this resource"
    )

def require_not_staff(current_user: dict) -> dict:
    """Require user is not staff (owner or admin)"""
    if current_user.get("role") == "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff cannot access this resource"
        )
    return current_user

def require_staff_read_only(current_user: dict) -> dict:
    """Allow staff to read but not modify (used for GET endpoints)"""
    # Staff can read, but write operations should use require_not_staff
    return current_user

def check_staff_appointment_access(
    current_user: dict,
    appointment_staff_id: Optional[int]
) -> bool:
    """Check if staff user can access this appointment"""
    if current_user.get("role") != "staff":
        return True  # Non-staff users have access
    
    user_staff_id = current_user.get("staff_id")
    if user_staff_id is None:
        return False  # Staff user without staff_id cannot access
    
    return appointment_staff_id == user_staff_id

# HTML route authentication helper
async def get_current_user_for_html(request: Request):
    """Get current user for HTML routes - reads token from Authorization header"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        # Try to get from cookie as fallback
        token = request.cookies.get("access_token")
        if not token:
            return None
    else:
        token = auth_header.replace("Bearer ", "")
    
    payload = decode_token(token)
    if payload is None:
        return None
    
    user_id_str = payload.get("sub")
    token_business_id_str = payload.get("business_id")
    
    if user_id_str is None or token_business_id_str is None:
        return None
    
    try:
        user_id = int(user_id_str)
        token_business_id = int(token_business_id_str)
    except (ValueError, TypeError):
        return None
    
    try:
        db_pool = await get_db()
    except RuntimeError:
        return None
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, email, full_name, role, created_at, updated_at FROM users WHERE id = %s AND business_id = %s LIMIT 1",
                (user_id, token_business_id)
            )
            user = await cursor.fetchone()
            if user is None:
                return None
            
            # Staff rolü için staff_id bilgisini ekle
            if user["role"] == "staff":
                await cursor.execute(
                    "SELECT id FROM staff WHERE user_id = %s AND business_id = %s LIMIT 1",
                    (user_id, token_business_id)
                )
                staff = await cursor.fetchone()
                if staff:
                    user["staff_id"] = staff["id"]
                else:
                    user["staff_id"] = None
            else:
                user["staff_id"] = None
            
            return user

async def require_auth_for_html(request: Request, allowed_roles: Optional[list[str]] = None):
    """Require authentication for HTML routes - returns user or redirects"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    
    if allowed_roles and user.get("role") not in allowed_roles:
        # Redirect to dashboard instead of 403 for HTML routes
        return RedirectResponse(url="/dashboard", status_code=302)
    
    return user
