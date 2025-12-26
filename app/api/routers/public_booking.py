from fastapi import APIRouter, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.db import get_connection, get_db
from app.services.appointment_service import check_double_booking
from app.models.schemas import PublicBookingCreate
from typing import List, Optional
from datetime import datetime, date
import aiomysql
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# IMPORTANT: More specific routes (with sub-paths) must be defined BEFORE more general routes
# Otherwise FastAPI will match the general route first

@router.get("/api/public/booking/{token}/available-slots", summary="Get available slots for public booking", description="Get available appointment slots for public booking form (no authentication required)")
async def get_public_available_slots(
    token: str,
    staff_id: int = Query(..., description="Staff ID"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    service_ids: Optional[List[int]] = Query(None, description="Optional list of service IDs to calculate slot duration")
):
    """Get available slots for public booking form"""
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Verify booking link exists and is active
                await cursor.execute(
                    """SELECT id, business_id, service_ids, staff_ids, start_date, end_date, 
                    max_uses, current_uses, is_active
                    FROM booking_links WHERE token = %s LIMIT 1""",
                    (token,)
                )
                booking_link = await cursor.fetchone()
                
                if not booking_link:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Booking link not found"
                    )
                
                if not booking_link['is_active']:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Booking link is not active"
                    )
                
                business_id = booking_link['business_id']
                
                # Validate staff_id against booking link filter
                link_staff_ids = None
                if booking_link['staff_ids']:
                    link_staff_ids = json.loads(booking_link['staff_ids'])
                
                if link_staff_ids and staff_id not in link_staff_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected staff is not allowed for this booking link"
                    )
                
                # Validate service_ids against booking link filter
                link_service_ids = None
                if booking_link['service_ids']:
                    link_service_ids = json.loads(booking_link['service_ids'])
                
                if link_service_ids and service_ids:
                    if not all(sid in link_service_ids for sid in service_ids):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="One or more selected services are not allowed for this booking link"
                        )
                
                # Use availability service
                from app.services.availability_service import get_available_slots
                from app.db import get_db
                db_pool = await get_db()
                
                result = await get_available_slots(
                    business_id=business_id,
                    staff_id=staff_id,
                    date=date,
                    db_pool=db_pool,
                    service_ids=service_ids
                )
                
                return result
                
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    except Exception as e:
        logger.exception("Error fetching public available slots")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch available slots: {str(e)}"
        )

@router.post("/api/public/booking/{token}/create", summary="Create appointment via public booking link", description="Create a pending appointment from public booking form (no authentication required)")
async def create_public_booking(
    token: str,
    booking_data: PublicBookingCreate
):
    """Create a pending appointment from public booking link"""
    if not booking_data.service_ids or len(booking_data.service_ids) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one service must be selected"
        )
    
    if not booking_data.staff_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staff must be selected"
        )
    
    if not booking_data.appointment_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment date is required"
        )
    
    try:
        async with get_connection() as conn:
            appointment_id = None
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Lock booking link row to prevent concurrent usage limit violations
                    await cursor.execute(
                        """SELECT id, business_id, service_ids, staff_ids, start_date, end_date, 
                        max_uses, current_uses, is_active
                        FROM booking_links WHERE token = %s FOR UPDATE""",
                        (token,)
                    )
                    booking_link = await cursor.fetchone()
                    
                    if not booking_link:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Booking link not found"
                        )
                    
                    # Validate booking link is active
                    if not booking_link['is_active']:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Booking link is not active"
                        )
                    
                    # Validate date range
                    today = date.today()
                    if booking_link['start_date'] and booking_link['start_date'] > today:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Booking link is not yet active"
                        )
                    
                    if booking_link['end_date'] and booking_link['end_date'] < today:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Booking link has expired"
                        )
                    
                    # Validate usage limit (with lock, so concurrent requests are safe)
                    if booking_link['max_uses'] and booking_link['current_uses'] >= booking_link['max_uses']:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Booking link has reached its usage limit"
                        )
                    
                    business_id = booking_link['business_id']
                    
                    # Validate service_ids against booking link filter
                    link_service_ids = None
                    if booking_link['service_ids']:
                        link_service_ids = json.loads(booking_link['service_ids'])
                    
                    if link_service_ids:
                        # All submitted service_ids must be in the allowed list
                        if not all(sid in link_service_ids for sid in booking_data.service_ids):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="One or more selected services are not allowed for this booking link"
                            )
                    
                    # Validate staff_id against booking link filter
                    link_staff_ids = None
                    if booking_link['staff_ids']:
                        link_staff_ids = json.loads(booking_link['staff_ids'])
                    
                    if link_staff_ids:
                        if booking_data.staff_id not in link_staff_ids:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Selected staff is not allowed for this booking link"
                            )
                    
                    # Validate services belong to business and are active
                    unique_service_ids = list(dict.fromkeys(booking_data.service_ids))
                    placeholders = ','.join(['%s'] * len(unique_service_ids))
                    await cursor.execute(
                        f"""SELECT id, price FROM services 
                        WHERE id IN ({placeholders}) AND business_id = %s AND is_active = 1""",
                        (*unique_service_ids, business_id)
                    )
                    services = await cursor.fetchall()
                    
                    if len(services) != len(unique_service_ids):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="One or more services are invalid or inactive"
                        )
                    
                    # Validate staff belongs to business and is active
                    await cursor.execute(
                        "SELECT id FROM staff WHERE id = %s AND business_id = %s AND is_active = 1 LIMIT 1",
                        (booking_data.staff_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Selected staff is invalid or inactive"
                        )
                    
                    # Upsert customer (find by email or create new)
                    await cursor.execute(
                        "SELECT id FROM customers WHERE business_id = %s AND email = %s LIMIT 1",
                        (business_id, booking_data.customer_email)
                    )
                    customer = await cursor.fetchone()
                    
                    if customer:
                        customer_id = customer['id']
                        # Update customer info if provided
                        if booking_data.customer_phone:
                            await cursor.execute(
                                "UPDATE customers SET phone = %s, full_name = %s WHERE id = %s",
                                (booking_data.customer_phone, booking_data.customer_name, customer_id)
                            )
                        else:
                            await cursor.execute(
                                "UPDATE customers SET full_name = %s WHERE id = %s",
                                (booking_data.customer_name, customer_id)
                            )
                    else:
                        # Create new customer
                        await cursor.execute(
                            "INSERT INTO customers (business_id, email, phone, full_name) VALUES (%s, %s, %s, %s)",
                            (business_id, booking_data.customer_email, booking_data.customer_phone, booking_data.customer_name)
                        )
                        customer_id = cursor.lastrowid
                    
                    # Parse appointment date
                    try:
                        appointment_datetime = datetime.fromisoformat(booking_data.appointment_date.replace('Z', '+00:00'))
                    except:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid appointment date format"
                        )
                    
                    # Double-booking check (reuse existing logic)
                    is_available, conflicting = await check_double_booking(
                        business_id=business_id,
                        staff_id=booking_data.staff_id,
                        appointment_date=appointment_datetime,
                        service_ids=unique_service_ids,
                        cursor=cursor,
                        exclude_appointment_id=None
                    )
                    
                    if not is_available:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Time slot is not available. Conflicting appointment: {conflicting}"
                        )
                    
                    # Insert appointment with status='pending'
                    await cursor.execute(
                        """INSERT INTO appointments 
                        (business_id, customer_id, staff_id, appointment_date, status, notes)
                        VALUES (%s, %s, %s, %s, 'pending', %s)""",
                        (business_id, customer_id, booking_data.staff_id, appointment_datetime, booking_data.notes)
                    )
                    appointment_id = cursor.lastrowid
                    
                    # Insert appointment_services
                    for service in services:
                        await cursor.execute(
                            "INSERT INTO appointment_services (appointment_id, service_id, price) VALUES (%s, %s, %s)",
                            (appointment_id, service['id'], service['price'])
                        )
                    
                    # Increment booking link usage
                    await cursor.execute(
                        "UPDATE booking_links SET current_uses = current_uses + 1 WHERE id = %s",
                        (booking_link['id'],)
                    )
                
                await conn.commit()
                
                return {
                    "message": "Appointment request submitted successfully. It will be reviewed and confirmed.",
                    "appointment_id": appointment_id
                }
                
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error creating public booking")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create appointment: {str(e)}"
                )
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.get("/public/booking/{token}", response_class=HTMLResponse, summary="Public booking page", description="Public booking form page (no authentication required)")
async def public_booking_page(request: Request, token: str):
    """Public booking page - displays form for customers to book appointments"""
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Fetch booking link
                await cursor.execute(
                    """SELECT id, business_id, token, name, description, service_ids, staff_ids,
                    start_date, end_date, max_uses, current_uses, is_active
                    FROM booking_links WHERE token = %s LIMIT 1""",
                    (token,)
                )
                booking_link = await cursor.fetchone()
                
                if not booking_link:
                    return templates.TemplateResponse("booking/public/not_found.html", {
                        "request": request,
                        "message": "Booking link not found"
                    })
                
                # Validate booking link
                if not booking_link['is_active']:
                    return templates.TemplateResponse("booking/public/not_found.html", {
                        "request": request,
                        "message": "This booking link is no longer active"
                    })
                
                # Check date range
                today = date.today()
                if booking_link['start_date'] and booking_link['start_date'] > today:
                    return templates.TemplateResponse("booking/public/not_found.html", {
                        "request": request,
                        "message": "This booking link is not yet active"
                    })
                
                if booking_link['end_date'] and booking_link['end_date'] < today:
                    return templates.TemplateResponse("booking/public/not_found.html", {
                        "request": request,
                        "message": "This booking link has expired"
                    })
                
                # Check usage limit
                if booking_link['max_uses'] and booking_link['current_uses'] >= booking_link['max_uses']:
                    return templates.TemplateResponse("booking/public/not_found.html", {
                        "request": request,
                        "message": "This booking link has reached its usage limit"
                    })
                
                # Parse JSON fields
                service_ids = None
                if booking_link['service_ids']:
                    service_ids = json.loads(booking_link['service_ids'])
                
                staff_ids = None
                if booking_link['staff_ids']:
                    staff_ids = json.loads(booking_link['staff_ids'])
                
                # Fetch allowed services
                if service_ids:
                    placeholders = ','.join(['%s'] * len(service_ids))
                    await cursor.execute(
                        f"""SELECT id, name, description, duration_minutes, price 
                        FROM services WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1
                        ORDER BY name""",
                        (booking_link['business_id'], *service_ids)
                    )
                else:
                    await cursor.execute(
                        """SELECT id, name, description, duration_minutes, price 
                        FROM services WHERE business_id = %s AND is_active = 1
                        ORDER BY name""",
                        (booking_link['business_id'],)
                    )
                services = await cursor.fetchall()
                
                # Fetch allowed staff
                if staff_ids:
                    placeholders = ','.join(['%s'] * len(staff_ids))
                    await cursor.execute(
                        f"""SELECT id, full_name, email, phone 
                        FROM staff WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1
                        ORDER BY full_name""",
                        (booking_link['business_id'], *staff_ids)
                    )
                else:
                    await cursor.execute(
                        """SELECT id, full_name, email, phone 
                        FROM staff WHERE business_id = %s AND is_active = 1
                        ORDER BY full_name""",
                        (booking_link['business_id'],)
                    )
                staff = await cursor.fetchall()
                
                return templates.TemplateResponse("booking/public/form.html", {
                    "request": request,
                    "booking_link": booking_link,
                    "services": services,
                    "staff": staff,
                    "token": token
                })
                
    except RuntimeError:
        return templates.TemplateResponse("booking/public/error.html", {
            "request": request,
            "message": "Service temporarily unavailable"
        })
    except Exception as e:
        logger.exception("Error loading public booking page")
        return templates.TemplateResponse("booking/public/error.html", {
            "request": request,
            "message": "An error occurred"
        })

@router.get("/api/public/booking/{token}", summary="Get booking link metadata", description="Get booking link metadata for public UI (no authentication required)")
async def get_public_booking_link(token: str):
    """Get booking link metadata for public booking form"""
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """SELECT id, business_id, token, name, description, service_ids, staff_ids,
                    start_date, end_date, max_uses, current_uses, is_active
                    FROM booking_links WHERE token = %s LIMIT 1""",
                    (token,)
                )
                booking_link = await cursor.fetchone()
                
                if not booking_link:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Booking link not found"
                    )
                
                # Validate active status
                if not booking_link['is_active']:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Booking link is not active"
                    )
                
                # Validate date range
                today = date.today()
                if booking_link['start_date'] and booking_link['start_date'] > today:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Booking link is not yet active"
                    )
                
                if booking_link['end_date'] and booking_link['end_date'] < today:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Booking link has expired"
                    )
                
                # Validate usage limit
                if booking_link['max_uses'] and booking_link['current_uses'] >= booking_link['max_uses']:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Booking link has reached its usage limit"
                    )
                
                # Parse JSON fields
                service_ids = None
                if booking_link['service_ids']:
                    service_ids = json.loads(booking_link['service_ids'])
                
                staff_ids = None
                if booking_link['staff_ids']:
                    staff_ids = json.loads(booking_link['staff_ids'])
                
                # Fetch allowed services
                if service_ids:
                    placeholders = ','.join(['%s'] * len(service_ids))
                    await cursor.execute(
                        f"""SELECT id, name, description, duration_minutes, price 
                        FROM services WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1
                        ORDER BY name""",
                        (booking_link['business_id'], *service_ids)
                    )
                else:
                    await cursor.execute(
                        """SELECT id, name, description, duration_minutes, price 
                        FROM services WHERE business_id = %s AND is_active = 1
                        ORDER BY name""",
                        (booking_link['business_id'],)
                    )
                services = await cursor.fetchall()
                
                # Fetch allowed staff
                if staff_ids:
                    placeholders = ','.join(['%s'] * len(staff_ids))
                    await cursor.execute(
                        f"""SELECT id, full_name, email, phone 
                        FROM staff WHERE business_id = %s AND id IN ({placeholders}) AND is_active = 1
                        ORDER BY full_name""",
                        (booking_link['business_id'], *staff_ids)
                    )
                else:
                    await cursor.execute(
                        """SELECT id, full_name, email, phone 
                        FROM staff WHERE business_id = %s AND is_active = 1
                        ORDER BY full_name""",
                        (booking_link['business_id'],)
                    )
                staff = await cursor.fetchall()
                
                return {
                    "booking_link": {
                        "id": booking_link['id'],
                        "name": booking_link['name'],
                        "description": booking_link['description'],
                        "service_ids": service_ids,
                        "staff_ids": staff_ids
                    },
                    "services": services,
                    "staff": staff
                }
                
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    except Exception as e:
        logger.exception("Error fetching public booking link")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch booking link: {str(e)}"
        )

