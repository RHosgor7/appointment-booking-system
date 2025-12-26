from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies import get_current_user, require_not_staff
from app.db import get_db
from app.models.schemas import StaffCreate, StaffUpdate, StaffResponse
from app.auth import get_password_hash
from typing import List
import aiomysql

# Güvenli pymysql import - IntegrityError tuple pattern
try:
    import pymysql.err
    IntegrityErrors = (pymysql.err.IntegrityError,)
except Exception:
    IntegrityErrors = ()

router = APIRouter()

@router.post("/", response_model=StaffResponse, summary="Create staff", description="Create a new staff member for the authenticated business")
async def create_staff(
    staff_data: StaffCreate,
    current_user: dict = Depends(get_current_user)
):
    # Staff cannot access staff management
    require_not_staff(current_user)
    
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Role kontrolü - Panel Access sadece owner tarafından verilebilir
    user_role = current_user.get("role")
    if staff_data.panel_access and user_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner can grant panel access"
        )
    
    # Panel Access açıksa validasyon
    if staff_data.panel_access:
        if not staff_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required when Panel Access is enabled"
            )
        if not staff_data.role or staff_data.role not in ["admin", "staff"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid role (admin or staff) is required when Panel Access is enabled"
            )
        if not staff_data.password or len(staff_data.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required and must be at least 8 characters long when Panel Access is enabled"
            )
    
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        staff_id = None
        user_id = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Panel Access = ON: Önce user oluştur
                if staff_data.panel_access:
                    # Email unique kontrolü (business bazlı)
                    await cursor.execute(
                        "SELECT id FROM users WHERE business_id = %s AND email = %s LIMIT 1",
                        (business_id, staff_data.email)
                    )
                    if await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Email already exists"
                        )
                    
                    # Password hash oluştur
                    password_hash = get_password_hash(staff_data.password)
                    
                    # User oluştur
                    await cursor.execute(
                        "INSERT INTO users (business_id, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, %s)",
                        (business_id, staff_data.email, password_hash, staff_data.full_name, staff_data.role)
                    )
                    user_id = cursor.lastrowid
                
                # Staff oluştur
                await cursor.execute(
                    "INSERT INTO staff (business_id, user_id, full_name, email, phone, is_active) VALUES (%s, %s, %s, %s, %s, %s)",
                    (business_id, user_id, staff_data.full_name, staff_data.email, staff_data.phone, staff_data.is_active)
                )
                staff_id = cursor.lastrowid
            
            await conn.commit()
        except HTTPException:
            # Commit öncesi HTTPException (rollback gerekli)
            await conn.rollback()
            raise
        except IntegrityErrors as e:
            # IntegrityError ayrı except bloğu
            await conn.rollback()
            
            # MySQL duplicate key error code 1062 kontrolü
            error_code = e.args[0] if e.args else None
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                error_code = None
            
            if error_code == 1062:
                # Duplicate email => 409 Conflict
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Staff already exists"
                )
            else:
                # Diğer IntegrityError'lar (FK vs) => 400 Bad Request
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid staff data"
                )
        except Exception as e:
            # MySQL duplicate fallback kontrolü (pymysql import edilemezse)
            await conn.rollback()
            
            error_msg = str(e).lower()
            error_code = e.args[0] if e.args else None
            
            # error_code'u int'e dönüştür
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                pass
            
            # MySQL duplicate key error code 1062 veya "Duplicate entry" mesajı
            is_duplicate = (
                error_code == 1062 or
                'duplicate entry' in error_msg or
                'duplicate key' in error_msg
            )
            
            if is_duplicate:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Staff already exists"
                )
            
            # Diğer hatalar => 500 Internal Server Error
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create staff"
            )
        
        # Commit sonrası SELECT (tenant-safe, rollback yok)
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, user_id, full_name, email, phone, is_active, created_at, updated_at FROM staff WHERE id = %s AND business_id = %s LIMIT 1",
                (staff_id, business_id)
            )
            staff = await cursor.fetchone()
            
            if not staff:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created staff"
                )
            
            return staff

@router.get("/", response_model=List[StaffResponse], summary="List staff", description="Get all staff members for the authenticated business")
async def list_staff(
    current_user: dict = Depends(get_current_user),
    search: str = Query(None, description="Search by name or email")
):
    # Staff cannot access staff management
    require_not_staff(current_user)
    
    # business_id kontrolü
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
            if search:
                # Search by name or email
                await cursor.execute(
                    "SELECT id, business_id, user_id, full_name, email, phone, is_active, created_at, updated_at FROM staff WHERE business_id = %s AND (full_name LIKE %s OR email LIKE %s) ORDER BY full_name ASC LIMIT 50",
                    (business_id, f"%{search}%", f"%{search}%")
                )
            else:
                await cursor.execute(
                    "SELECT id, business_id, user_id, full_name, email, phone, is_active, created_at, updated_at FROM staff WHERE business_id = %s ORDER BY created_at DESC",
                    (business_id,)
                )
            staff_list = await cursor.fetchall()
            return staff_list

@router.get("/{staff_id}", response_model=StaffResponse, summary="Get staff", description="Get a single staff member by ID")
async def get_staff(
    staff_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Tek bir personeli ID ile getirir.
    """
    # Staff cannot access staff management
    require_not_staff(current_user)
    
    # business_id kontrolü
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
                "SELECT id, business_id, user_id, full_name, email, phone, is_active, created_at, updated_at FROM staff WHERE id = %s AND business_id = %s LIMIT 1",
                (staff_id, business_id)
            )
            staff = await cursor.fetchone()
            
            if not staff:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Staff not found"
                )
            
            return staff

@router.put("/{staff_id}", response_model=StaffResponse, summary="Update staff", description="Update an existing staff member")
async def update_staff(
    staff_id: int,
    staff_data: StaffUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Mevcut personeli günceller.
    """
    # Staff cannot access staff management
    require_not_staff(current_user)
    
    # business_id kontrolü
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
        staff = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Mevcut personeli kontrol et (tenant-safe)
                await cursor.execute(
                    "SELECT id FROM staff WHERE id = %s AND business_id = %s LIMIT 1",
                    (staff_id, business_id)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Staff not found"
                    )
                
                # Güncellenecek alanları belirle
                update_fields = []
                update_values = []
                
                if staff_data.full_name is not None:
                    update_fields.append("full_name = %s")
                    update_values.append(staff_data.full_name)
                if staff_data.email is not None:
                    update_fields.append("email = %s")
                    update_values.append(staff_data.email)
                if staff_data.phone is not None:
                    update_fields.append("phone = %s")
                    update_values.append(staff_data.phone)
                if staff_data.is_active is not None:
                    update_fields.append("is_active = %s")
                    update_values.append(staff_data.is_active)
                
                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )
                
                # UPDATE query
                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_values.append(staff_id)
                update_values.append(business_id)
                
                update_query = f"UPDATE staff SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
            
            # Commit sonrası SELECT (tenant-safe)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT id, business_id, user_id, full_name, email, phone, is_active, created_at, updated_at FROM staff WHERE id = %s AND business_id = %s LIMIT 1",
                    (staff_id, business_id)
                )
                staff = await cursor.fetchone()
                
                if not staff:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve updated staff"
                    )
            
            return staff
            
        except HTTPException:
            await conn.rollback()
            raise
        except IntegrityErrors as e:
            await conn.rollback()
            error_code = e.args[0] if e.args else None
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                error_code = None
            
            if error_code == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Staff already exists"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid staff data"
                )
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update staff: {str(e)}"
            )
