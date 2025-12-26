from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies import get_current_user, require_not_staff
from app.db import get_db
from app.models.schemas import BusinessSettingsUpdate, BusinessSettingsResponse
from datetime import time
import aiomysql

router = APIRouter()

@router.get("/", response_model=BusinessSettingsResponse, summary="Get business settings", description="Get business settings for the authenticated business")
async def get_business_settings(
    current_user: dict = Depends(get_current_user)
):
    # Staff cannot access settings
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
                """
                SELECT id, business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours,
                       working_hours_start, working_hours_end, timezone, created_at, updated_at
                FROM business_settings
                WHERE business_id = %s LIMIT 1
                """,
                (business_id,)
            )
            settings = await cursor.fetchone()
            
            if not settings:
                # Default settings oluştur
                await conn.begin()
                try:
                    await cursor.execute(
                        """
                        INSERT INTO business_settings 
                        (business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours,
                         working_hours_start, working_hours_end, timezone)
                        VALUES (%s, 30, 15, 24, '09:00:00', '18:00:00', 'Europe/Istanbul')
                        """,
                        (business_id,)
                    )
                    await conn.commit()
                    
                    # Yeni oluşturulan settings'i getir
                    await cursor.execute(
                        """
                        SELECT id, business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours,
                               working_hours_start, working_hours_end, timezone, created_at, updated_at
                        FROM business_settings
                        WHERE business_id = %s LIMIT 1
                        """,
                        (business_id,)
                    )
                    settings = await cursor.fetchone()
                except Exception as e:
                    await conn.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to create default settings"
                    )
            
            # TIME alanlarını time objesine çevir (Pydantic otomatik serialize edecek)
            # MySQL'den TIME tipi genellikle timedelta veya time objesi olarak gelir
            from datetime import timedelta
            
            # working_hours_start
            start_time_raw = settings.get("working_hours_start")
            if start_time_raw is not None and start_time_raw != '':
                if isinstance(start_time_raw, str):
                    # String format: "HH:MM:SS" veya "HH:MM"
                    parts = start_time_raw.split(':')
                    h, m = int(parts[0]), int(parts[1])
                    s = int(parts[2]) if len(parts) > 2 else 0
                    settings["working_hours_start"] = time(h, m, s)
                elif isinstance(start_time_raw, time):
                    # Zaten time objesi
                    settings["working_hours_start"] = start_time_raw
                elif isinstance(start_time_raw, timedelta):
                    # timedelta'dan time'a çevir
                    total_seconds = int(start_time_raw.total_seconds())
                    h = total_seconds // 3600
                    m = (total_seconds % 3600) // 60
                    s = total_seconds % 60
                    settings["working_hours_start"] = time(h, m, s)
                else:
                    # Bilinmeyen format, default kullan
                    settings["working_hours_start"] = time(9, 0, 0)
            else:
                # NULL veya boş, default kullan
                settings["working_hours_start"] = time(9, 0, 0)
            
            # working_hours_end
            end_time_raw = settings.get("working_hours_end")
            if end_time_raw is not None and end_time_raw != '':
                if isinstance(end_time_raw, str):
                    # String format: "HH:MM:SS" veya "HH:MM"
                    parts = end_time_raw.split(':')
                    h, m = int(parts[0]), int(parts[1])
                    s = int(parts[2]) if len(parts) > 2 else 0
                    settings["working_hours_end"] = time(h, m, s)
                elif isinstance(end_time_raw, time):
                    # Zaten time objesi
                    settings["working_hours_end"] = end_time_raw
                elif isinstance(end_time_raw, timedelta):
                    # timedelta'dan time'a çevir
                    total_seconds = int(end_time_raw.total_seconds())
                    h = total_seconds // 3600
                    m = (total_seconds % 3600) // 60
                    s = total_seconds % 60
                    settings["working_hours_end"] = time(h, m, s)
                else:
                    # Bilinmeyen format, default kullan
                    settings["working_hours_end"] = time(18, 0, 0)
            else:
                # NULL veya boş, default kullan
                settings["working_hours_end"] = time(18, 0, 0)
            
            # Debug: Log the values to see what we're getting
            print(f"DEBUG: working_hours_start raw: {start_time_raw}, type: {type(start_time_raw)}, parsed: {settings['working_hours_start']}")
            print(f"DEBUG: working_hours_end raw: {end_time_raw}, type: {type(end_time_raw)}, parsed: {settings['working_hours_end']}")
            
            return settings

@router.put("/", response_model=BusinessSettingsResponse, summary="Update business settings", description="Update business settings for the authenticated business")
async def update_business_settings(
    settings_data: BusinessSettingsUpdate,
    current_user: dict = Depends(get_current_user)
):
    # Staff cannot access settings
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
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Önce settings var mı kontrol et
                await cursor.execute(
                    "SELECT id FROM business_settings WHERE business_id = %s LIMIT 1",
                    (business_id,)
                )
                existing = await cursor.fetchone()
                
                # Update edilecek alanları hazırla
                update_fields = []
                update_values = []
                
                if settings_data.slot_length_minutes is not None:
                    update_fields.append("slot_length_minutes = %s")
                    update_values.append(settings_data.slot_length_minutes)
                
                if settings_data.buffer_time_minutes is not None:
                    update_fields.append("buffer_time_minutes = %s")
                    update_values.append(settings_data.buffer_time_minutes)
                
                if settings_data.cancellation_hours is not None:
                    update_fields.append("cancellation_hours = %s")
                    update_values.append(settings_data.cancellation_hours)
                
                if settings_data.working_hours_start is not None:
                    update_fields.append("working_hours_start = %s")
                    update_values.append(settings_data.working_hours_start.strftime('%H:%M:%S'))
                
                if settings_data.working_hours_end is not None:
                    update_fields.append("working_hours_end = %s")
                    update_values.append(settings_data.working_hours_end.strftime('%H:%M:%S'))
                
                if settings_data.timezone is not None:
                    update_fields.append("timezone = %s")
                    update_values.append(settings_data.timezone)
                
                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )
                
                if existing:
                    # UPDATE
                    update_values.append(business_id)
                    query = f"""
                        UPDATE business_settings
                        SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP
                        WHERE business_id = %s
                    """
                    await cursor.execute(query, tuple(update_values))
                else:
                    # INSERT (default değerlerle)
                    default_slot = settings_data.slot_length_minutes if settings_data.slot_length_minutes is not None else 30
                    default_buffer = settings_data.buffer_time_minutes if settings_data.buffer_time_minutes is not None else 15
                    default_cancellation = settings_data.cancellation_hours if settings_data.cancellation_hours is not None else 24
                    default_start = settings_data.working_hours_start.strftime('%H:%M:%S') if settings_data.working_hours_start else '09:00:00'
                    default_end = settings_data.working_hours_end.strftime('%H:%M:%S') if settings_data.working_hours_end else '18:00:00'
                    default_timezone = settings_data.timezone if settings_data.timezone else 'Europe/Istanbul'
                    
                    await cursor.execute(
                        """
                        INSERT INTO business_settings 
                        (business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours,
                         working_hours_start, working_hours_end, timezone)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (business_id, default_slot, default_buffer, default_cancellation, default_start, default_end, default_timezone)
                    )
            
            await conn.commit()
        except HTTPException:
            await conn.rollback()
            raise
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update settings: {str(e)}"
            )
        
        # Güncellenmiş settings'i getir
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                """
                SELECT id, business_id, slot_length_minutes, buffer_time_minutes, cancellation_hours,
                       working_hours_start, working_hours_end, timezone, created_at, updated_at
                FROM business_settings
                WHERE business_id = %s LIMIT 1
                """,
                (business_id,)
            )
            settings = await cursor.fetchone()
            
            if not settings:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve updated settings"
                )
            
            # TIME alanlarını time objesine çevir (aynı mantık GET endpoint'inde olduğu gibi)
            from datetime import timedelta
            
            # working_hours_start
            start_time_raw = settings.get("working_hours_start")
            if start_time_raw is not None and start_time_raw != '':
                if isinstance(start_time_raw, str):
                    parts = start_time_raw.split(':')
                    h, m = int(parts[0]), int(parts[1])
                    s = int(parts[2]) if len(parts) > 2 else 0
                    settings["working_hours_start"] = time(h, m, s)
                elif isinstance(start_time_raw, time):
                    settings["working_hours_start"] = start_time_raw
                elif isinstance(start_time_raw, timedelta):
                    total_seconds = int(start_time_raw.total_seconds())
                    h = total_seconds // 3600
                    m = (total_seconds % 3600) // 60
                    s = total_seconds % 60
                    settings["working_hours_start"] = time(h, m, s)
                else:
                    settings["working_hours_start"] = time(9, 0, 0)
            else:
                settings["working_hours_start"] = time(9, 0, 0)
            
            # working_hours_end
            end_time_raw = settings.get("working_hours_end")
            if end_time_raw is not None and end_time_raw != '':
                if isinstance(end_time_raw, str):
                    parts = end_time_raw.split(':')
                    h, m = int(parts[0]), int(parts[1])
                    s = int(parts[2]) if len(parts) > 2 else 0
                    settings["working_hours_end"] = time(h, m, s)
                elif isinstance(end_time_raw, time):
                    settings["working_hours_end"] = end_time_raw
                elif isinstance(end_time_raw, timedelta):
                    total_seconds = int(end_time_raw.total_seconds())
                    h = total_seconds // 3600
                    m = (total_seconds % 3600) // 60
                    s = total_seconds % 60
                    settings["working_hours_end"] = time(h, m, s)
                else:
                    settings["working_hours_end"] = time(18, 0, 0)
            else:
                settings["working_hours_end"] = time(18, 0, 0)
            
            # Debug: Log the values
            print(f"DEBUG UPDATE: working_hours_end raw: {end_time_raw}, type: {type(end_time_raw)}, parsed: {settings['working_hours_end']}")
            
            return settings

