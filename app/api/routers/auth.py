from fastapi import APIRouter, HTTPException, Depends, status
from app.models.schemas import UserRegister, UserLogin, TokenResponse, UserResponse, PasswordResetRequest, PasswordResetResponse, NewPasswordRequest
from app.auth import get_password_hash, create_access_token, verify_password
from app.db import get_db
from app.dependencies import get_current_user
import aiomysql

# Güvenli pymysql import
try:
    import pymysql.err
    IntegrityError = pymysql.err.IntegrityError
except ImportError:
    IntegrityError = None

router = APIRouter()

@router.post("/register", response_model=TokenResponse, summary="Register a new business", description="Create a new business account and receive a JWT token")
async def register(user_data: UserRegister):
    db_pool = await get_db()
    
    async with db_pool.acquire() as conn:
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Email kontrolü (business email unique)
                await cursor.execute(
                    "SELECT id FROM businesses WHERE email = %s LIMIT 1",
                    (user_data.email,)
                )
                if await cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Email already exists"
                    )
                
                # User email kontrolü
                await cursor.execute(
                    "SELECT id FROM users WHERE email = %s LIMIT 1",
                    (user_data.email,)
                )
                if await cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Email already exists"
                    )
                
                # Business oluştur
                await cursor.execute(
                    "INSERT INTO businesses (name, email) VALUES (%s, %s)",
                    (user_data.business_name, user_data.email)
                )
                business_id = cursor.lastrowid
                
                # User oluştur
                password_hash = get_password_hash(user_data.password)
                await cursor.execute(
                    "INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, 'owner')",
                    (business_id, user_data.email, password_hash, user_data.full_name)
                )
                user_id = cursor.lastrowid
                
                # Business settings oluştur
                await cursor.execute(
                    "INSERT INTO business_settings (business_id) VALUES (%s)",
                    (business_id,)
                )
                
                await conn.commit()
                
                # JWT token oluştur (sub ve business_id ile)
                access_token = create_access_token(data={
                    "sub": str(user_id),
                    "business_id": business_id
                })
                return {"access_token": access_token, "token_type": "bearer"}
        except HTTPException:
            await conn.rollback()
            raise
        except Exception as e:
            await conn.rollback()
            if IntegrityError and isinstance(e, IntegrityError):
                raise HTTPException(
                    status_code=409,
                    detail="Email already exists"
                )
            raise HTTPException(
                status_code=500,
                detail="Registration failed"
            )

@router.post("/login", response_model=TokenResponse, summary="Login", description="Authenticate and receive a JWT token")
async def login(login_data: UserLogin):
    db_pool = await get_db()
    
    if db_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database pool is not initialized"
        )
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT id, business_id, email, password_hash, full_name, role FROM users WHERE email = %s LIMIT 1",
                    (login_data.email,)
                )
                user = await cursor.fetchone()
                
                if not user or not verify_password(login_data.password, user["password_hash"]):
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid credentials"
                    )
                
                # JWT token oluştur (sub ve business_id ile)
                access_token = create_access_token(data={
                    "sub": str(user["id"]),
                    "business_id": user["business_id"]
                })
                return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        # Log the error for debugging
        import traceback
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="Login failed"
        )

@router.get("/me", response_model=UserResponse, summary="Get current user", description="Get the current authenticated user's information")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user information"""
    return current_user

@router.post("/reset-password", response_model=PasswordResetResponse, summary="Request password reset", description="Request a password reset for the given email")
async def reset_password(request: PasswordResetRequest):
    """Request password reset - validates email exists"""
    db_pool = await get_db()
    
    if db_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database pool is not initialized"
        )
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Check if user exists
                await cursor.execute(
                    "SELECT id, email FROM users WHERE email = %s LIMIT 1",
                    (request.email,)
                )
                user = await cursor.fetchone()
                
                # Always return success message (security best practice - don't reveal if email exists)
                # In production, you would send an email with a reset link/token here
                return {"message": "If the email exists, you will receive a password reset link."}
                
    except Exception as e:
        # Log error but still return generic message
        import traceback
        print(f"Password reset request error: {str(e)}")
        print(traceback.format_exc())
        return {"message": "If the email exists, you will receive a password reset link."}

@router.post("/new-password", response_model=PasswordResetResponse, summary="Set new password", description="Set a new password with verification code")
async def set_new_password(request: NewPasswordRequest):
    """Set new password after verification code check"""
    db_pool = await get_db()
    
    if db_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database pool is not initialized"
        )
    
    # Validate code (must be "123456" for now)
    if request.code != "123456":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )
    
    # Validate password match
    if request.password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match"
        )
    
    # Validate password length
    if len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Check if user exists
                await cursor.execute(
                    "SELECT id, email FROM users WHERE email = %s LIMIT 1",
                    (request.email,)
                )
                user = await cursor.fetchone()
                
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found"
                    )
                
                # Update password
                password_hash = get_password_hash(request.password)
                await cursor.execute(
                    "UPDATE users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
                    (password_hash, user["id"])
                )
                await conn.commit()
                
                return {"message": "Password has been reset successfully!"}
                
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Password reset error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )
