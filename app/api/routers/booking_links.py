from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from app.dependencies import get_current_user, require_not_staff
from app.db import get_connection
from app.models.schemas import BookingLinkCreate, BookingLinkUpdate, BookingLinkResponse
from typing import List, Optional
import aiomysql
import logging
import secrets
import json

logger = logging.getLogger(__name__)

router = APIRouter()

def generate_token() -> str:
    """Generate a cryptographically secure random token for booking links"""
    return secrets.token_urlsafe(32)  # 32 bytes = 43 characters URL-safe

@router.post("/", response_model=BookingLinkResponse, summary="Create booking link", description="Create a new booking link for the authenticated business")
async def create_booking_link(
    booking_link_data: BookingLinkCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new booking link"""
    # Staff cannot access booking links
    require_not_staff(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        async with get_connection() as conn:
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Generate unique token
                    token = generate_token()
                    # Ensure uniqueness (retry if collision, though extremely unlikely)
                    max_retries = 5
                    for _ in range(max_retries):
                        await cursor.execute(
                            "SELECT id FROM booking_links WHERE token = %s LIMIT 1",
                            (token,)
                        )
                        if not await cursor.fetchone():
                            break
                        token = generate_token()
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to generate unique token"
                        )
                    
                    # Validate service_ids if provided
                    service_ids_json = None
                    if booking_link_data.service_ids:
                        if len(booking_link_data.service_ids) == 0:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="service_ids cannot be empty array. Use null for all services."
                            )
                        # Verify all services belong to this business and are active
                        placeholders = ','.join(['%s'] * len(booking_link_data.service_ids))
                        await cursor.execute(
                            f"SELECT id FROM services WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1",
                            (business_id, *booking_link_data.service_ids)
                        )
                        found_services = await cursor.fetchall()
                        if len(found_services) != len(booking_link_data.service_ids):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="One or more service_ids are invalid or inactive"
                            )
                        service_ids_json = json.dumps(booking_link_data.service_ids)
                    
                    # Validate staff_ids if provided
                    staff_ids_json = None
                    if booking_link_data.staff_ids:
                        if len(booking_link_data.staff_ids) == 0:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="staff_ids cannot be empty array. Use null for all staff."
                            )
                        # Verify all staff belong to this business and are active
                        placeholders = ','.join(['%s'] * len(booking_link_data.staff_ids))
                        await cursor.execute(
                            f"SELECT id FROM staff WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1",
                            (business_id, *booking_link_data.staff_ids)
                        )
                        found_staff = await cursor.fetchall()
                        if len(found_staff) != len(booking_link_data.staff_ids):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="One or more staff_ids are invalid or inactive"
                            )
                        staff_ids_json = json.dumps(booking_link_data.staff_ids)
                    
                    # Insert booking link
                    await cursor.execute(
                        """INSERT INTO booking_links 
                        (business_id, token, name, description, service_ids, staff_ids, start_date, end_date, max_uses, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (business_id, token, booking_link_data.name, booking_link_data.description, service_ids_json, staff_ids_json, 
                         booking_link_data.start_date, booking_link_data.end_date, booking_link_data.max_uses, 1 if booking_link_data.is_active else 0)
                    )
                    booking_link_id = cursor.lastrowid
                
                await conn.commit()
                
                # Fetch created booking link
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """SELECT id, business_id, token, name, description, service_ids, staff_ids, 
                        start_date, end_date, max_uses, current_uses, is_active, created_at, updated_at
                        FROM booking_links WHERE id = %s AND business_id = %s LIMIT 1""",
                        (booking_link_id, business_id)
                    )
                    booking_link = await cursor.fetchone()
                    
                    if not booking_link:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve created booking link"
                        )
                    
                    # Parse JSON fields
                    if booking_link['service_ids']:
                        booking_link['service_ids'] = json.loads(booking_link['service_ids'])
                    else:
                        booking_link['service_ids'] = None
                    
                    if booking_link['staff_ids']:
                        booking_link['staff_ids'] = json.loads(booking_link['staff_ids'])
                    else:
                        booking_link['staff_ids'] = None
                    
                    # Convert date objects to ISO format strings
                    if booking_link.get('start_date'):
                        if not isinstance(booking_link['start_date'], str):
                            booking_link['start_date'] = booking_link['start_date'].isoformat() if hasattr(booking_link['start_date'], 'isoformat') else str(booking_link['start_date'])
                    else:
                        booking_link['start_date'] = None
                    
                    if booking_link.get('end_date'):
                        if not isinstance(booking_link['end_date'], str):
                            booking_link['end_date'] = booking_link['end_date'].isoformat() if hasattr(booking_link['end_date'], 'isoformat') else str(booking_link['end_date'])
                    else:
                        booking_link['end_date'] = None
                    
                    return booking_link
                    
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error creating booking link")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create booking link: {str(e)}"
                )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.get("/", response_model=List[BookingLinkResponse], summary="List booking links", description="Get all booking links for the authenticated business")
async def list_booking_links(
    current_user: dict = Depends(get_current_user)
):
    """List all booking links for the business"""
    # Staff cannot access booking links
    require_not_staff(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """SELECT id, business_id, token, name, description, service_ids, staff_ids,
                    start_date, end_date, max_uses, current_uses, is_active, created_at, updated_at
                    FROM booking_links WHERE business_id = %s ORDER BY created_at DESC""",
                    (business_id,)
                )
                booking_links = await cursor.fetchall()
                
                # Parse JSON fields and convert date objects to strings
                for link in booking_links:
                    try:
                        if link['service_ids']:
                            if isinstance(link['service_ids'], str):
                                link['service_ids'] = json.loads(link['service_ids'])
                            elif isinstance(link['service_ids'], (list, dict)):
                                # Already parsed
                                pass
                            else:
                                link['service_ids'] = None
                        else:
                            link['service_ids'] = None
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse service_ids for booking link {link.get('id')}: {e}")
                        link['service_ids'] = None
                    
                    try:
                        if link['staff_ids']:
                            if isinstance(link['staff_ids'], str):
                                link['staff_ids'] = json.loads(link['staff_ids'])
                            elif isinstance(link['staff_ids'], (list, dict)):
                                # Already parsed
                                pass
                            else:
                                link['staff_ids'] = None
                        else:
                            link['staff_ids'] = None
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse staff_ids for booking link {link.get('id')}: {e}")
                        link['staff_ids'] = None
                    
                    # Convert date objects to ISO format strings
                    if link.get('start_date'):
                        if isinstance(link['start_date'], str):
                            # Already a string
                            pass
                        else:
                            # datetime.date or datetime.datetime object
                            link['start_date'] = link['start_date'].isoformat() if hasattr(link['start_date'], 'isoformat') else str(link['start_date'])
                    else:
                        link['start_date'] = None
                    
                    if link.get('end_date'):
                        if isinstance(link['end_date'], str):
                            # Already a string
                            pass
                        else:
                            # datetime.date or datetime.datetime object
                            link['end_date'] = link['end_date'].isoformat() if hasattr(link['end_date'], 'isoformat') else str(link['end_date'])
                    else:
                        link['end_date'] = None
                
                return booking_links
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    except Exception as e:
        logger.exception(f"Error listing booking links: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list booking links: {str(e)}"
        )

@router.get("/{booking_link_id}", response_model=BookingLinkResponse, summary="Get booking link", description="Get a single booking link by ID")
async def get_booking_link(
    booking_link_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get a single booking link"""
    # Staff cannot access booking links
    require_not_staff(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """SELECT id, business_id, token, name, description, service_ids, staff_ids,
                    start_date, end_date, max_uses, current_uses, is_active, created_at, updated_at
                    FROM booking_links WHERE id = %s AND business_id = %s LIMIT 1""",
                    (booking_link_id, business_id)
                )
                booking_link = await cursor.fetchone()
                
                if not booking_link:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Booking link not found"
                    )
                
                # Parse JSON fields
                if booking_link['service_ids']:
                    booking_link['service_ids'] = json.loads(booking_link['service_ids'])
                else:
                    booking_link['service_ids'] = None
                
                if booking_link['staff_ids']:
                    booking_link['staff_ids'] = json.loads(booking_link['staff_ids'])
                else:
                    booking_link['staff_ids'] = None
                
                # Convert date objects to ISO format strings
                if booking_link.get('start_date'):
                    if not isinstance(booking_link['start_date'], str):
                        booking_link['start_date'] = booking_link['start_date'].isoformat() if hasattr(booking_link['start_date'], 'isoformat') else str(booking_link['start_date'])
                else:
                    booking_link['start_date'] = None
                
                if booking_link.get('end_date'):
                    if not isinstance(booking_link['end_date'], str):
                        booking_link['end_date'] = booking_link['end_date'].isoformat() if hasattr(booking_link['end_date'], 'isoformat') else str(booking_link['end_date'])
                else:
                    booking_link['end_date'] = None
                
                return booking_link
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.put("/{booking_link_id}", response_model=BookingLinkResponse, summary="Update booking link", description="Update an existing booking link")
async def update_booking_link(
    booking_link_id: int,
    booking_link_data: BookingLinkUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update a booking link"""
    # Staff cannot access booking links
    require_not_staff(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        async with get_connection() as conn:
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if booking link exists
                    await cursor.execute(
                        "SELECT id FROM booking_links WHERE id = %s AND business_id = %s LIMIT 1",
                        (booking_link_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Booking link not found"
                        )
                    
                    # Build update query dynamically
                    update_fields = []
                    update_values = []
                    
                    if booking_link_data.name is not None:
                        update_fields.append("name = %s")
                        update_values.append(booking_link_data.name)
                    
                    if booking_link_data.description is not None:
                        update_fields.append("description = %s")
                        update_values.append(booking_link_data.description)
                    
                    if booking_link_data.service_ids is not None:
                        if len(booking_link_data.service_ids) == 0:
                            update_fields.append("service_ids = NULL")
                        else:
                            # Validate services
                            placeholders = ','.join(['%s'] * len(booking_link_data.service_ids))
                            await cursor.execute(
                                f"SELECT id FROM services WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1",
                                (business_id, *booking_link_data.service_ids)
                            )
                            found_services = await cursor.fetchall()
                            if len(found_services) != len(booking_link_data.service_ids):
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="One or more service_ids are invalid or inactive"
                                )
                            update_fields.append("service_ids = %s")
                            update_values.append(json.dumps(booking_link_data.service_ids))
                    
                    if booking_link_data.staff_ids is not None:
                        if len(booking_link_data.staff_ids) == 0:
                            update_fields.append("staff_ids = NULL")
                        else:
                            # Validate staff
                            placeholders = ','.join(['%s'] * len(booking_link_data.staff_ids))
                            await cursor.execute(
                                f"SELECT id FROM staff WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1",
                                (business_id, *booking_link_data.staff_ids)
                            )
                            found_staff = await cursor.fetchall()
                            if len(found_staff) != len(booking_link_data.staff_ids):
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="One or more staff_ids are invalid or inactive"
                                )
                            update_fields.append("staff_ids = %s")
                            update_values.append(json.dumps(booking_link_data.staff_ids))
                    
                    if booking_link_data.start_date is not None:
                        update_fields.append("start_date = %s")
                        update_values.append(booking_link_data.start_date)
                    
                    if booking_link_data.end_date is not None:
                        update_fields.append("end_date = %s")
                        update_values.append(booking_link_data.end_date)
                    
                    if booking_link_data.max_uses is not None:
                        update_fields.append("max_uses = %s")
                        update_values.append(booking_link_data.max_uses)
                    
                    if booking_link_data.is_active is not None:
                        update_fields.append("is_active = %s")
                        update_values.append(1 if booking_link_data.is_active else 0)
                    
                    if not update_fields:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No fields to update"
                        )
                    
                    update_fields.append("updated_at = CURRENT_TIMESTAMP")
                    update_values.append(booking_link_id)
                    update_values.append(business_id)
                    
                    update_query = f"UPDATE booking_links SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                    await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
                
                # Fetch updated booking link
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """SELECT id, business_id, token, name, description, service_ids, staff_ids,
                        start_date, end_date, max_uses, current_uses, is_active, created_at, updated_at
                        FROM booking_links WHERE id = %s AND business_id = %s LIMIT 1""",
                        (booking_link_id, business_id)
                    )
                    booking_link = await cursor.fetchone()
                    
                    if booking_link:
                        # Parse JSON fields
                        if booking_link['service_ids']:
                            booking_link['service_ids'] = json.loads(booking_link['service_ids'])
                        else:
                            booking_link['service_ids'] = None
                        
                        if booking_link['staff_ids']:
                            booking_link['staff_ids'] = json.loads(booking_link['staff_ids'])
                        else:
                            booking_link['staff_ids'] = None
                        
                        # Convert date objects to ISO format strings
                        if booking_link.get('start_date'):
                            if not isinstance(booking_link['start_date'], str):
                                booking_link['start_date'] = booking_link['start_date'].isoformat() if hasattr(booking_link['start_date'], 'isoformat') else str(booking_link['start_date'])
                        else:
                            booking_link['start_date'] = None
                        
                        if booking_link.get('end_date'):
                            if not isinstance(booking_link['end_date'], str):
                                booking_link['end_date'] = booking_link['end_date'].isoformat() if hasattr(booking_link['end_date'], 'isoformat') else str(booking_link['end_date'])
                        else:
                            booking_link['end_date'] = None
                    
                    return booking_link
                    
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error updating booking link")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update booking link: {str(e)}"
                )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.delete("/{booking_link_id}", summary="Delete booking link", description="Delete a booking link")
async def delete_booking_link(
    booking_link_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Delete a booking link"""
    # Staff cannot access booking links
    require_not_staff(current_user)
    
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    try:
        async with get_connection() as conn:
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if booking link exists
                    await cursor.execute(
                        "SELECT id FROM booking_links WHERE id = %s AND business_id = %s LIMIT 1",
                        (booking_link_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Booking link not found"
                        )
                    
                    # Delete booking link
                    await cursor.execute(
                        "DELETE FROM booking_links WHERE id = %s AND business_id = %s",
                        (booking_link_id, business_id)
                    )
                
                await conn.commit()
                return {"message": "Booking link deleted successfully"}
                
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error deleting booking link")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to delete booking link: {str(e)}"
                )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

