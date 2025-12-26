from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies import get_current_user, require_owner
from app.db import get_db
from app.models.schemas import UserCreate, UserUpdate, UserListResponse, UserResponse
from app.auth import get_password_hash
from typing import List, Optional
import aiomysql

# Güvenli pymysql import
try:
    import pymysql.err
    IntegrityError = pymysql.err.IntegrityError
except ImportError:
    IntegrityError = None

router = APIRouter()

@router.get("/", response_model=List[UserListResponse], summary="List users", description="Get all users for the authenticated business")
async def list_users(
    current_user: dict = Depends(get_current_user),
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role (admin, staff, owner)")
):
    """
    List all users for the current business with staff profile information.
    Only owner can access this endpoint.
    """
    # Only owner can access users management
    require_owner(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Base query with LEFT JOIN to staff
            base_query = """
                SELECT 
                    u.id,
                    u.business_id,
                    u.email,
                    u.full_name,
                    u.role,
                    u.created_at,
                    u.updated_at,
                    CASE WHEN s.id IS NOT NULL THEN TRUE ELSE FALSE END as has_staff_profile,
                    s.id as staff_id
                FROM users u
                LEFT JOIN staff s ON s.user_id = u.id AND s.business_id = u.business_id
                WHERE u.business_id = %s
            """
            
            params = [business_id]
            conditions = []
            
            # Search filter
            if search:
                conditions.append("(u.full_name LIKE %s OR u.email LIKE %s)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param])
            
            # Role filter
            if role:
                conditions.append("u.role = %s")
                params.append(role)
            
            if conditions:
                base_query += " AND " + " AND ".join(conditions)
            
            base_query += " ORDER BY u.created_at DESC"
            
            await cursor.execute(base_query, params)
            users = await cursor.fetchall()
            
            # Convert boolean to proper type
            for user in users:
                user['has_staff_profile'] = bool(user.get('has_staff_profile', False))
            
            return users

@router.post("/", response_model=UserResponse, summary="Create user", description="Create a new user (owner and admin only)")
async def create_user(
    user_data: UserCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new user. Only owner can create users.
    If link_to_staff_id is provided, links the user to an existing staff profile.
    """
    # Only owner can create users
    require_owner(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Password validation
    if not user_data.password or len(user_data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        user_id = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Email unique kontrolü (global unique constraint)
                await cursor.execute(
                    "SELECT id FROM users WHERE email = %s LIMIT 1",
                    (user_data.email,)
                )
                if await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already exists"
                    )
                
                # Password hash oluştur
                password_hash = get_password_hash(user_data.password)
                
                # User oluştur
                await cursor.execute(
                    "INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, %s)",
                    (business_id, user_data.email, password_hash, user_data.full_name, user_data.role)
                )
                user_id = cursor.lastrowid
                
                # Link to staff if provided
                if user_data.link_to_staff_id:
                    # Lock staff row for update
                    await cursor.execute(
                        "SELECT id, business_id, user_id FROM staff WHERE id = %s FOR UPDATE",
                        (user_data.link_to_staff_id,)
                    )
                    staff = await cursor.fetchone()
                    
                    if not staff:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Staff not found"
                        )
                    
                    # Verify business_id matches
                    if staff['business_id'] != business_id:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Staff does not belong to your business"
                        )
                    
                    # Verify user_id is NULL
                    if staff['user_id'] is not None:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Staff profile is already linked to a user"
                        )
                    
                    # Update staff with user_id
                    await cursor.execute(
                        "UPDATE staff SET user_id = %s WHERE id = %s AND business_id = %s",
                        (user_id, user_data.link_to_staff_id, business_id)
                    )
            
            await conn.commit()
            
        except HTTPException:
            await conn.rollback()
            raise
        except IntegrityError as e:
            await conn.rollback()
            error_code = e.args[0] if e.args else None
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                error_code = None
            
            if error_code == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user"
            )
        except Exception as e:
            await conn.rollback()
            error_msg = str(e).lower()
            if 'duplicate' in error_msg or 'unique' in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create user: {str(e)}"
            )
        
        # Fetch created user
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, email, full_name, role, created_at, updated_at FROM users WHERE id = %s AND business_id = %s LIMIT 1",
                (user_id, business_id)
            )
            user = await cursor.fetchone()
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created user"
                )
            
            return user

@router.get("/{user_id}", response_model=UserListResponse, summary="Get user", description="Get a single user by ID with staff profile information")
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Get a single user by ID. Only owner and admin can access.
    """
    # Only owner can access users management
    require_owner(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT 
                    u.id,
                    u.business_id,
                    u.email,
                    u.full_name,
                    u.role,
                    u.created_at,
                    u.updated_at,
                    CASE WHEN s.id IS NOT NULL THEN TRUE ELSE FALSE END as has_staff_profile,
                    s.id as staff_id
                FROM users u
                LEFT JOIN staff s ON s.user_id = u.id AND s.business_id = u.business_id
                WHERE u.id = %s AND u.business_id = %s
                LIMIT 1
                """,
                (user_id, business_id)
            )
            user = await cursor.fetchone()
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user['has_staff_profile'] = bool(user.get('has_staff_profile', False))
            return user

