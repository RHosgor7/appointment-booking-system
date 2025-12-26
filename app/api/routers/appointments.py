from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from app.dependencies import get_current_user
from app.db import get_db, get_connection, execute_with_retry
from app.models.schemas import AppointmentCreate, AppointmentUpdate, AppointmentStatusUpdate, AppointmentResponse, AppointmentServiceNestedResponse, AvailableSlotsResponse
from app.services.appointment_service import check_double_booking
from typing import List, Optional, Union
import aiomysql
import logging

logger = logging.getLogger(__name__)

# Güvenli pymysql import - IntegrityError tuple pattern
try:
    import pymysql.err
    IntegrityErrors = (pymysql.err.IntegrityError,)
except Exception:
    IntegrityErrors = ()

router = APIRouter()

@router.post("/", response_model=AppointmentResponse, summary="Create appointment", description="Create a new appointment with double-booking prevention")
async def create_appointment(
    appointment_data: AppointmentCreate,
    current_user: dict = Depends(get_current_user)
):
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Use get_connection() context manager for connection with ping check
    try:
        async with get_connection() as conn:
            appointment_id = None
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Customer ve Staff'ın aynı business'a ait olduğunu kontrol et
                    await cursor.execute(
                        "SELECT id FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                        (appointment_data.customer_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Customer not found"
                        )
                    
                    await cursor.execute(
                        "SELECT id FROM staff WHERE id = %s AND business_id = %s AND is_active = TRUE LIMIT 1",
                        (appointment_data.staff_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Staff not found or inactive"
                        )
                    
                    # Service IDs'yi normalize et (duplicate'leri kaldır)
                    unique_service_ids = list(dict.fromkeys(appointment_data.service_ids))
                    
                    # unique_service_ids boş ise hata ver
                    if not unique_service_ids:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="service_ids is required"
                        )
                    
                    # Service'lerin aynı business'a ait olduğunu ve aktif olduğunu kontrol et
                    placeholders = ','.join(['%s'] * len(unique_service_ids))
                    await cursor.execute(
                        f"SELECT id, price FROM services WHERE id IN ({placeholders}) AND business_id = %s AND is_active = TRUE",
                        (*unique_service_ids, business_id)
                    )
                    services = await cursor.fetchall()
                    
                    if len(services) != len(unique_service_ids):
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="One or more services not found or inactive"
                        )
                    
                    # Double-booking kontrolü (buffer time dahil)
                    # Transaction içinde, SELECT FOR UPDATE ile locking yaparak race condition riskini azaltır.
                    # Not: DB seviyesindeki UNIQUE KEY (unique_business_staff_datetime) yalnızca "aynı start time"ı
                    # engeller; overlap (buffer time dahil) çakışmaları için tek başına yeterli değildir.
                    # Bu kontrol buffer time dahil overlap kontrolü sağlar.
                    try:
                        is_available, conflicting = await check_double_booking(
                            business_id=business_id,
                            staff_id=appointment_data.staff_id,
                            appointment_date=appointment_data.appointment_date,
                            service_ids=unique_service_ids,
                            cursor=cursor,  # Aynı transaction içindeki cursor
                            exclude_appointment_id=None  # Create senaryosu, exclude yok
                        )
                        if not is_available:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail=f"Staff is not available at this time. Conflicting appointments: {len(conflicting)}"
                            )
                    except ValueError as e:
                        # check_double_booking ValueError fırlatırsa (service_ids boş, service bulunamadı vb.)
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(e)
                        )
                    
                    # Appointment oluştur
                    # Not: unique_business_staff_datetime UNIQUE KEY yalnızca aynı start time'ı engeller,
                    # overlap kontrolü için yeterli değildir (yukarıdaki check_double_booking gerekli).
                    await cursor.execute(
                        "INSERT INTO appointments (business_id, customer_id, staff_id, appointment_date, status, notes, admin_note, staff_note, customer_note) VALUES (%s, %s, %s, %s, 'scheduled', %s, %s, %s, %s)",
                        (business_id, appointment_data.customer_id, appointment_data.staff_id, appointment_data.appointment_date, appointment_data.notes, appointment_data.admin_note, appointment_data.staff_note, appointment_data.customer_note)
                    )
                    appointment_id = cursor.lastrowid
                    
                    # Appointment services ekle (her service için price ile)
                    service_price_map = {s['id']: s['price'] for s in services}
                    for service_id in unique_service_ids:
                        service_price = service_price_map[service_id]
                        await cursor.execute(
                            "INSERT INTO appointment_services (appointment_id, service_id, price) VALUES (%s, %s, %s)",
                            (appointment_id, service_id, service_price)
                        )
                
                await conn.commit()
                
            except HTTPException:
                # Commit öncesi HTTPException (rollback gerekli)
                await conn.rollback()
                raise
            except IntegrityErrors as e:
                # IntegrityError ayrı except bloğu (double-booking veya FK hatası)
                await conn.rollback()
                
                # MySQL duplicate key error code 1062 kontrolü
                error_code = e.args[0] if e.args else None
                try:
                    error_code = int(error_code)
                except (TypeError, ValueError):
                    error_code = None
                
                if error_code == 1062:
                    # Double-booking => 409 Conflict
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Staff is already booked at this time"
                    )
                else:
                    # Diğer IntegrityError'lar (FK vs) => 400 Bad Request
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid appointment data"
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
                        detail="Staff is already booked at this time"
                    )
                
                # Diğer hatalar => 500 Internal Server Error
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create appointment"
                )
            
            # B) Response read: yeni cursor ile appointment + names + services select et
            # Note: appointment_id None kontrolü
            if appointment_id is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create appointment: appointment_id is None"
                )
            
            # Aşama B: Commit sonrası read-only işlemler
            # ÖNEMLİ: Bu aşamada begin/rollback YOK - zaten commit edildi
            # Aynı conn kullanılıyor (stable, commit sonrası da geçerli)
            try:
                # Commit sonrası SELECT (tenant-safe, rollback yok - yeni cursor ile)
                # Note: conn.begin() çağrılmıyor, rollback çağrılmıyor
                async with conn.cursor(aiomysql.DictCursor) as cursor2:
                    # Appointment bilgilerini customer ve staff full_name'leri ile birlikte çek
                    await cursor2.execute(
                        """
                        SELECT 
                            a.id, a.business_id, a.customer_id, a.staff_id, 
                            a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                            a.created_at, a.updated_at,
                            c.full_name AS customer_full_name,
                            s.full_name AS staff_full_name
                        FROM appointments a
                        LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                        LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                        WHERE a.id = %s AND a.business_id = %s
                        LIMIT 1
                        """,
                        (business_id, business_id, appointment_id, business_id)
                    )
                    appointment = await cursor2.fetchone()
                    
                    if not appointment:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve created appointment"
                        )
                    
                    # Services bilgilerini çek (LEFT JOIN kullanarak services olmasa bile appointment dönsün)
                    await cursor2.execute(
                        """
                        SELECT 
                            aps.service_id,
                            s.name,
                            s.duration_minutes,
                            aps.price,
                            aps.created_at
                        FROM appointments a
                        LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                        LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                        WHERE a.business_id = %s AND a.id = %s
                        ORDER BY aps.created_at
                        """,
                        (business_id, appointment_id)
                    )
                    services_data = await cursor2.fetchall()
                    
                    # Services alanını ekle (NULL service_id'leri filtrele)
                    # Deterministik: Her zaman list döndür (hiç yoksa boş liste)
                    appointment['services'] = [
                        {
                            'service_id': s['service_id'],
                            'name': s['name'],
                            'duration_minutes': s['duration_minutes'],
                            'price': s['price'],
                            'created_at': s['created_at']
                        }
                        for s in services_data if s['service_id'] is not None
                    ]
                    # Eğer services hiç yoksa boş liste garantisi
                    if not appointment.get('services'):
                        appointment['services'] = []
                    
                    # Transaction bilgisini çek (eğer varsa) - LEFT JOIN ile tek query'de
                    try:
                        await cursor2.execute(
                            """
                            SELECT 
                                t.id, t.business_id, t.appointment_id, t.customer_id, 
                                t.amount, t.payment_method, t.status, t.transaction_date, t.created_at
                            FROM appointments a
                            LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = a.business_id
                            WHERE a.id = %s AND a.business_id = %s
                            LIMIT 1
                            """,
                            (appointment_id, business_id)
                        )
                        result = await cursor2.fetchone()
                        
                        if result and result.get('id') is not None:  # Transaction exists (t.id is not NULL)
                            appointment['transaction'] = {
                                'id': result['id'],
                                'amount': float(result['amount']),
                                'payment_method': result['payment_method'],
                                'status': result['status'],
                                'transaction_date': result['transaction_date'].isoformat() if result['transaction_date'] else None,
                                'created_at': result['created_at'].isoformat() if result['created_at'] else None
                            }
                        else:
                            appointment['transaction'] = None
                    except Exception as e:
                        # If transaction query fails, set transaction to None (don't break the appointment response)
                        logger.warning(f"Failed to fetch transaction for appointment {appointment_id}: {str(e)}")
                        appointment['transaction'] = None
                    
                    return appointment
            except HTTPException:
                # Re-raise HTTPException as-is
                raise
            except Exception as e:
                # B aşamasında hata -> rollback yok (zaten commit edildi) -> 500
                logger.error(f"Failed to retrieve created appointment {appointment_id}: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created appointment"
                )
    except RuntimeError as e:
        # get_connection() RuntimeError fırlatırsa (pool not initialized)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.get("/", response_model=List[AppointmentResponse], summary="List appointments", description="Get all appointments for the authenticated business, optionally including services")
async def list_appointments(
    request: Request,  # For accessing request URL - must be first (no default value)
    current_user: dict = Depends(get_current_user),
    include_services: bool = Query(False, description="Include appointment services"),
    include_names: bool = Query(True, description="Include customer and staff full names"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD, exclusive)"),
    staff_id: Optional[List[int]] = Query(None, description="Filter by staff ID (can be multiple)"),
    customer_id: Optional[List[int]] = Query(None, description="Filter by customer ID (can be multiple)"),
    statuses: Optional[List[str]] = Query(None, alias="status", description="Filter by status (can be multiple)"),
    service_id: Optional[List[int]] = Query(None, description="Filter by service ID (can be multiple)")
):
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Staff role kontrolü - staff sadece kendi appointmentlarını görebilir
    user_role = current_user.get("role")
    if user_role == "staff":
        user_staff_id = current_user.get("staff_id")
        if user_staff_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff user must have a linked staff profile"
            )
        # Staff için staff_id filtresini zorunlu kıl (frontend'den gelen filtreyi override et)
        staff_id = [user_staff_id]
    
    # Log request URL for debugging
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Query string: {request.url.query}")
    
    # FastAPI automatically converts single values to lists for List[int] parameters
    # So staff_id, customer_id, service_id are already lists or None
    # statuses is also already a list or None (using alias="status" for query parameter)
    
    # Debug logging - log raw parameters
    logger.info("=" * 80)
    logger.info("FILTER DEBUG - Raw parameters received:")
    logger.info(f"  staff_id: {staff_id} (type: {type(staff_id)})")
    logger.info(f"  customer_id: {customer_id} (type: {type(customer_id)})")
    logger.info(f"  statuses: {statuses} (type: {type(statuses)})")
    logger.info(f"  service_id: {service_id} (type: {type(service_id)})")
    logger.info(f"  start_date: {start_date}")
    logger.info(f"  end_date: {end_date}")
    logger.info("=" * 80)
    
    # Use get_connection() context manager for connection with ping check
    async with get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Build WHERE conditions dynamically
            where_conditions = ["a.business_id = %s"]
            query_params = [business_id]
            
            # Exclude pending and rejected appointments from list UNLESS they are explicitly requested in status filter
            # This allows appointment-requests page to fetch pending/rejected, but excludes them from regular appointments list
            should_exclude_pending_rejected = True
            if statuses is not None and len(statuses) > 0:
                # If status filter includes pending or rejected, don't exclude them (for appointment-requests page)
                if 'pending' in statuses or 'rejected' in statuses:
                    should_exclude_pending_rejected = False
            
            if should_exclude_pending_rejected:
                # Exclude pending and rejected (for appointments list page)
                where_conditions.append("a.status NOT IN ('pending', 'rejected')")
            
            # Date range filters
            if start_date:
                where_conditions.append("DATE(a.appointment_date) >= %s")
                query_params.append(start_date)
            if end_date:
                where_conditions.append("DATE(a.appointment_date) < %s")
                query_params.append(end_date)
            
            # Staff filter (can be multiple)
            if staff_id is not None and len(staff_id) > 0:
                placeholders = ','.join(['%s'] * len(staff_id))
                where_conditions.append(f"a.staff_id IN ({placeholders})")
                query_params.extend(staff_id)
                logger.info(f"  -> Added staff_id filter: IN ({placeholders}) with values: {staff_id}")
            
            # Customer filter (can be multiple)
            if customer_id is not None and len(customer_id) > 0:
                placeholders = ','.join(['%s'] * len(customer_id))
                where_conditions.append(f"a.customer_id IN ({placeholders})")
                query_params.extend(customer_id)
                logger.info(f"  -> Added customer_id filter: IN ({placeholders}) with values: {customer_id}")
            
            # Status filter (can be multiple) - using statuses variable (aliased as "status" in query)
            if statuses is not None and len(statuses) > 0:
                placeholders = ','.join(['%s'] * len(statuses))
                where_conditions.append(f"a.status IN ({placeholders})")
                query_params.extend(statuses)
                logger.info(f"  -> Added status filter: IN ({placeholders}) with values: {statuses}")
            
            # Service filter (requires JOIN with appointment_services)
            service_filter_join = ""
            if service_id is not None and len(service_id) > 0:
                service_filter_join = """
                    INNER JOIN appointment_services aps_filter ON aps_filter.appointment_id = a.id
                """
                placeholders = ','.join(['%s'] * len(service_id))
                where_conditions.append(f"aps_filter.service_id IN ({placeholders})")
                query_params.extend(service_id)
                logger.info(f"  -> Added service_id filter: IN ({placeholders}) with values: {service_id}")
            
            where_clause = " AND ".join(where_conditions)
            
            # Debug logging for WHERE clause
            logger.info("=" * 80)
            logger.info("SQL DEBUG - WHERE clause and parameters:")
            logger.info(f"  WHERE conditions count: {len(where_conditions)}")
            logger.info(f"  WHERE clause: {where_clause}")
            logger.info(f"  Query params count: {len(query_params)}")
            logger.info(f"  Query params: {query_params}")
            logger.info("=" * 80)
            
            # Base SELECT query oluştur
            if include_names:
                # JOIN ile customer ve staff full_name'leri ekle
                # DISTINCT kullanarak duplicate row'ları önle
                query = f"""
                    SELECT DISTINCT
                        a.id, a.business_id, a.customer_id, a.staff_id, 
                        a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                        a.created_at, a.updated_at,
                        c.full_name AS customer_full_name,
                        s.full_name AS staff_full_name
                    FROM appointments a
                    LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                    {service_filter_join}
                    WHERE {where_clause}
                    ORDER BY a.appointment_date ASC
                """
                # business_id'yi iki kez ekle (JOIN'ler için)
                final_params = [business_id, business_id] + query_params
                logger.info("=" * 80)
                logger.info("SQL DEBUG - Final query execution:")
                logger.info(f"  Final query:\n{query}")
                logger.info(f"  Final params count: {len(final_params)}")
                logger.info(f"  Final params: {final_params}")
                logger.info("=" * 80)
                await cursor.execute(query, tuple(final_params))
            else:
                # Sadece appointments tablosu
                query = f"""
                    SELECT id, business_id, customer_id, staff_id, 
                           appointment_date, status, notes, admin_note, staff_note, customer_note, 
                           created_at, updated_at
                    FROM appointments a
                    {service_filter_join}
                    WHERE {where_clause}
                    ORDER BY appointment_date ASC
                """
                logger.info("=" * 80)
                logger.info("SQL DEBUG - Final query execution (no names):")
                logger.info(f"  Final query:\n{query}")
                logger.info(f"  Final params count: {len(query_params)}")
                logger.info(f"  Final params: {query_params}")
                logger.info("=" * 80)
                await cursor.execute(query, tuple(query_params))
            
            appointments = await cursor.fetchall()
            
            logger.info("=" * 80)
            logger.info(f"SQL DEBUG - Query result: {len(appointments)} appointments found")
            logger.info("=" * 80)
            
            # include_services=true ise appointment_services + services bilgilerini ekle
            if include_services and appointments:
                appointment_ids = [appt['id'] for appt in appointments]
                
                # Tenant-safe query: appointments tablosu ile JOIN yaparak business_id kontrolü
                # LEFT JOIN kullanarak services olmasa bile appointment'ları döndür
                placeholders = ','.join(['%s'] * len(appointment_ids))
                services_query = f"""
                    SELECT 
                        aps.appointment_id,
                        aps.service_id,
                        s.name,
                        s.duration_minutes,
                        aps.price,
                        aps.created_at
                    FROM appointments a
                    LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                    LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id IN ({placeholders})
                    ORDER BY aps.appointment_id, aps.created_at
                """
                await cursor.execute(services_query, (business_id, *appointment_ids))
                services_data = await cursor.fetchall()
                
                # appointment_id'ye göre grupla (NULL service_id'leri filtrele)
                services_by_appointment = {}
                for service in services_data:
                    appointment_id = service['appointment_id']
                    # Skip if service_id is NULL (LEFT JOIN result when no appointment_services exists)
                    if service['service_id'] is None:
                        continue
                    if appointment_id not in services_by_appointment:
                        services_by_appointment[appointment_id] = []
                    services_by_appointment[appointment_id].append({
                        'service_id': service['service_id'],
                        'name': service['name'],
                        'duration_minutes': service['duration_minutes'],
                        'price': service['price'],
                        'created_at': service['created_at']
                    })
                
                # Her appointment'a services alanı ekle (services yoksa boş array)
                for appt in appointments:
                    appointment_id = appt['id']
                    if appointment_id in services_by_appointment:
                        appt['services'] = services_by_appointment[appointment_id]
                    else:
                        appt['services'] = []
            
            # include_names=false ise customer_full_name ve staff_full_name key'lerini kaldır
            if not include_names:
                for appt in appointments:
                    appt.pop('customer_full_name', None)
                    appt.pop('staff_full_name', None)
            
            # include_services=false ise services key'ini kaldır
            if not include_services:
                for appt in appointments:
                    appt.pop('services', None)
            
            return appointments

@router.get("/activities", response_model=List[AppointmentResponse], summary="Get activities", description="Get today's appointments for activities drawer. Staff sees only their appointments, Admin/Owner sees all appointments")
async def get_activities(
    limit: int = Query(10, ge=1, le=50, description="Maximum number of appointments to return"),
    current_user: dict = Depends(get_current_user)
):
    """
    Activities drawer için bugünün randevularını getirir.
    - Staff: Sadece bugünün kendi randevularını görür (user_id'ye bağlı staff_id)
    - Admin/Owner: Bugünün tüm randevularını görür
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Use get_connection() context manager for connection with ping check
    async with get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    # Staff user ama staff tablosunda kayıt yok, boş liste döndür
                    return []
                staff_id_filter = staff_result['id']
            
            # Query oluştur - Sadece bugünün randevuları
            if staff_id_filter:
                # Staff: Sadece bugünün kendi randevuları
                query = """
                    SELECT 
                        a.id, a.business_id, a.customer_id, a.staff_id, 
                        a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                        a.created_at, a.updated_at,
                        c.full_name AS customer_full_name,
                        s.full_name AS staff_full_name
                    FROM appointments a
                    LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                    WHERE a.business_id = %s 
                      AND a.staff_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                    ORDER BY a.appointment_date ASC
                    LIMIT %s
                """
                await cursor.execute(query, (business_id, business_id, business_id, staff_id_filter, limit))
            else:
                # Admin/Owner: Bugünün tüm randevuları
                query = """
                    SELECT 
                        a.id, a.business_id, a.customer_id, a.staff_id, 
                        a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                        a.created_at, a.updated_at,
                        c.full_name AS customer_full_name,
                        s.full_name AS staff_full_name
                    FROM appointments a
                    LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                    WHERE a.business_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                    ORDER BY a.appointment_date ASC
                    LIMIT %s
                """
                await cursor.execute(query, (business_id, business_id, business_id, limit))
            
            appointments = await cursor.fetchall()
            
            if not appointments:
                return []
            
            # Services bilgilerini çek (LEFT JOIN kullanarak services olmasa bile appointment dönsün)
            appointment_ids = [appt['id'] for appt in appointments]
            if appointment_ids:
                placeholders = ','.join(['%s'] * len(appointment_ids))
                await cursor.execute(
                    f"""
                    SELECT 
                        a.id as appointment_id,
                        aps.service_id,
                        s.name,
                        s.duration_minutes,
                        aps.price,
                        aps.created_at
                    FROM appointments a
                    LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                    LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id IN ({placeholders})
                    ORDER BY a.id, aps.created_at
                    """,
                    (business_id, *appointment_ids)
                )
                services_data = await cursor.fetchall()
                
                # Services'leri appointment'lara ekle (NULL service_id'leri filtrele)
                services_by_appointment = {}
                for service in services_data:
                    appointment_id = service['appointment_id']
                    # Skip if service_id is NULL (LEFT JOIN result when no appointment_services exists)
                    if service['service_id'] is None:
                        continue
                    if appointment_id not in services_by_appointment:
                        services_by_appointment[appointment_id] = []
                    services_by_appointment[appointment_id].append({
                        'service_id': service['service_id'],
                        'name': service['name'],
                        'duration_minutes': service['duration_minutes'],
                        'price': service['price'],
                        'created_at': service['created_at']
                    })
                
                for appt in appointments:
                    appointment_id = appt['id']
                    appt['services'] = services_by_appointment.get(appointment_id, [])
            else:
                for appt in appointments:
                    appt['services'] = []
            
            return appointments

@router.get("/available-slots", response_model=AvailableSlotsResponse, summary="Get available slots", description="Get available appointment slots for a staff member on a specific date")
async def get_available_slots_endpoint(
    staff_id: int = Query(..., description="Staff ID"),
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    service_ids: Optional[List[int]] = Query(None, description="Optional list of service IDs to calculate slot duration"),
    current_user: dict = Depends(get_current_user)
):
    """
    Belirli tarih ve staff için uygun slot'ları döndürür.
    Business settings'ten slot_length ve buffer_time alır.
    Mevcut randevuları ve buffer time'ı dikkate alarak gerçek uygunluk hesabı yapar.
    """
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
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from app.services.availability_service import get_available_slots
        result = await get_available_slots(
            business_id=business_id,
            staff_id=staff_id,
            date=date,
            db_pool=db_pool,
            service_ids=service_ids
        )
        return result
    except ValueError as e:
        # availability_service'den gelen ValueError'ları 400 Bad Request'e çevir
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log the full exception with stack trace
        logger.exception("Error in get_available_slots endpoint")
        
        # In development, return detailed error message
        import os
        is_dev = os.getenv("DEBUG", "True").lower() == "true"
        error_detail = str(e) if is_dev else "Failed to get available slots"
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail
        )

@router.get("/{appointment_id}", response_model=AppointmentResponse, summary="Get appointment", description="Get a single appointment by ID, optionally including services")
async def get_appointment(
    appointment_id: int,
    current_user: dict = Depends(get_current_user),
    include_services: bool = Query(True, description="Include appointment services")
):
    """
    Tek bir randevuyu ID ile getirir.
    """
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Staff role kontrolü - staff sadece kendi appointmentlarını görebilir
    user_role = current_user.get("role")
    user_staff_id = None
    if user_role == "staff":
        user_staff_id = current_user.get("staff_id")
        if user_staff_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff user must have a linked staff profile"
            )
    
    # Use get_connection() context manager for connection with ping check
    async with get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Appointment bilgilerini customer ve staff full_name'leri ile birlikte çek
            where_conditions = ["a.id = %s", "a.business_id = %s"]
            query_params = [appointment_id, business_id]
            
            # Staff için staff_id kontrolü ekle
            if user_role == "staff" and user_staff_id is not None:
                where_conditions.append("a.staff_id = %s")
                query_params.append(user_staff_id)
            
            where_clause = " AND ".join(where_conditions)
            
            await cursor.execute(
                f"""
                SELECT 
                    a.id, a.business_id, a.customer_id, a.staff_id, 
                    a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                    a.created_at, a.updated_at,
                    c.full_name AS customer_full_name,
                    s.full_name AS staff_full_name
                FROM appointments a
                LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                WHERE {where_clause}
                LIMIT 1
                """,
                (business_id, business_id, *query_params)
            )
            appointment = await cursor.fetchone()
            
            if not appointment:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Appointment not found"
                )
            
            # Services bilgilerini çek (include_services=True ise)
            if include_services:
                # LEFT JOIN kullanarak services olmasa bile appointment dönsün
                await cursor.execute(
                    """
                    SELECT 
                        aps.service_id,
                        s.name,
                        s.duration_minutes,
                        aps.price,
                        aps.created_at
                    FROM appointments a
                    LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                    LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id = %s
                    ORDER BY aps.created_at
                    """,
                    (business_id, appointment_id)
                )
                services_data = await cursor.fetchall()
                
                # Services alanını ekle (NULL service_id'leri filtrele)
                appointment['services'] = [
                    {
                        'service_id': s['service_id'],
                        'name': s['name'],
                        'duration_minutes': s['duration_minutes'],
                        'price': s['price'],
                        'created_at': s['created_at']
                    }
                    for s in services_data if s['service_id'] is not None
                ]
            else:
                appointment['services'] = None
            
            # Transaction bilgisini çek (eğer varsa) - LEFT JOIN ile tek query'de
            try:
                await cursor.execute(
                    """
                    SELECT 
                        t.id, t.business_id, t.appointment_id, t.customer_id, 
                        t.amount, t.payment_method, t.status, t.transaction_date, t.created_at
                    FROM appointments a
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = a.business_id
                    WHERE a.id = %s AND a.business_id = %s
                    LIMIT 1
                    """,
                    (appointment_id, business_id)
                )
                result = await cursor.fetchone()
                
                if result and result.get('id') is not None:  # Transaction exists (t.id is not NULL)
                    appointment['transaction'] = {
                        'id': result['id'],
                        'amount': float(result['amount']),
                        'payment_method': result['payment_method'],
                        'status': result['status'],
                        'transaction_date': result['transaction_date'].isoformat() if result['transaction_date'] else None,
                        'created_at': result['created_at'].isoformat() if result['created_at'] else None
                    }
                else:
                    appointment['transaction'] = None
            except Exception as e:
                # If transaction query fails, set transaction to None (don't break the appointment response)
                logger.warning(f"Failed to fetch transaction for appointment {appointment_id}: {str(e)}")
                appointment['transaction'] = None
            
            return appointment

@router.put("/{appointment_id}", response_model=AppointmentResponse, summary="Update appointment", description="Update an existing appointment with double-booking prevention")
async def update_appointment(
    appointment_id: int,
    appointment_data: AppointmentUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Mevcut randevuyu günceller. Double-booking kontrolü yapar.
    """
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Staff role kontrolü - staff sadece kendi appointmentlarını güncelleyebilir
    user_role = current_user.get("role")
    user_staff_id = None
    if user_role == "staff":
        user_staff_id = current_user.get("staff_id")
        if user_staff_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff user must have a linked staff profile"
            )
    
    # Use get_connection() context manager for connection with ping check
    async with get_connection() as conn:
        appointment = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Mevcut randevuyu kontrol et (tenant-safe)
                where_conditions = ["id = %s", "business_id = %s"]
                query_params = [appointment_id, business_id]
                
                # Staff için staff_id kontrolü ekle
                if user_role == "staff" and user_staff_id is not None:
                    where_conditions.append("staff_id = %s")
                    query_params.append(user_staff_id)
                
                where_clause = " AND ".join(where_conditions)
                
                await cursor.execute(
                    f"SELECT id, customer_id, staff_id, appointment_date, status FROM appointments WHERE {where_clause} LIMIT 1",
                    tuple(query_params)
                )
                existing_appointment = await cursor.fetchone()
                
                if not existing_appointment:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Appointment not found"
                    )
                
                # Staff için staff_id değiştirilemez
                if user_role == "staff" and appointment_data.staff_id is not None:
                    if appointment_data.staff_id != user_staff_id:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Staff cannot change appointment staff_id"
                        )
                
                # Note: Cancelled veya completed randevuları güncellemeye izin veriyoruz
                # çünkü status değişikliği yapılabilir (örneğin cancelled -> scheduled)
                
                # Güncellenecek değerleri belirle
                update_customer_id = appointment_data.customer_id if appointment_data.customer_id is not None else existing_appointment['customer_id']
                # Staff için staff_id değiştirilemez - her zaman mevcut staff_id kullan
                if user_role == "staff" and user_staff_id is not None:
                    update_staff_id = user_staff_id
                else:
                    update_staff_id = appointment_data.staff_id if appointment_data.staff_id is not None else existing_appointment['staff_id']
                update_appointment_date = appointment_data.appointment_date if appointment_data.appointment_date is not None else existing_appointment['appointment_date']
                
                # Customer ve Staff'ın aynı business'a ait olduğunu kontrol et
                await cursor.execute(
                    "SELECT id FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                    (update_customer_id, business_id)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Customer not found"
                    )
                
                await cursor.execute(
                    "SELECT id FROM staff WHERE id = %s AND business_id = %s AND is_active = TRUE LIMIT 1",
                    (update_staff_id, business_id)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Staff not found or inactive"
                    )
                
                # Service IDs güncelleniyorsa kontrol et
                if appointment_data.service_ids is not None:
                    unique_service_ids = list(dict.fromkeys(appointment_data.service_ids))
                    
                    if not unique_service_ids:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="service_ids cannot be empty"
                        )
                    
                    placeholders = ','.join(['%s'] * len(unique_service_ids))
                    await cursor.execute(
                        f"SELECT id, price FROM services WHERE id IN ({placeholders}) AND business_id = %s AND is_active = TRUE",
                        (*unique_service_ids, business_id)
                    )
                    services = await cursor.fetchall()
                    
                    if len(services) != len(unique_service_ids):
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="One or more services not found or inactive"
                        )
                else:
                    # Mevcut service_ids'i al
                    await cursor.execute(
                        "SELECT service_id FROM appointment_services WHERE appointment_id = %s",
                        (appointment_id,)
                    )
                    existing_services = await cursor.fetchall()
                    unique_service_ids = [s['service_id'] for s in existing_services]
                
                # Double-booking kontrolü (sadece date veya staff değiştiyse)
                if (appointment_data.appointment_date is not None or appointment_data.staff_id is not None or appointment_data.service_ids is not None):
                    try:
                        is_available, conflicting = await check_double_booking(
                            business_id=business_id,
                            staff_id=update_staff_id,
                            appointment_date=update_appointment_date,
                            service_ids=unique_service_ids,
                            cursor=cursor,
                            exclude_appointment_id=appointment_id  # Update senaryosu, mevcut randevuyu exclude et
                        )
                        if not is_available:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail=f"Staff is not available at this time. Conflicting appointments: {len(conflicting)}"
                            )
                    except ValueError as e:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(e)
                        )
                
                # Appointment'ı güncelle
                update_fields = []
                update_values = []
                
                if appointment_data.customer_id is not None:
                    update_fields.append("customer_id = %s")
                    update_values.append(appointment_data.customer_id)
                if appointment_data.staff_id is not None:
                    update_fields.append("staff_id = %s")
                    update_values.append(appointment_data.staff_id)
                if appointment_data.appointment_date is not None:
                    update_fields.append("appointment_date = %s")
                    update_values.append(appointment_data.appointment_date)
                if appointment_data.notes is not None:
                    update_fields.append("notes = %s")
                    update_values.append(appointment_data.notes)
                
                # admin_note ve staff_note için boş string'i None'a çevir
                if appointment_data.admin_note is not None:
                    admin_note_value = appointment_data.admin_note.strip() if appointment_data.admin_note and appointment_data.admin_note.strip() else None
                    update_fields.append("admin_note = %s")
                    update_values.append(admin_note_value)
                
                if appointment_data.staff_note is not None:
                    staff_note_value = appointment_data.staff_note.strip() if appointment_data.staff_note and appointment_data.staff_note.strip() else None
                    update_fields.append("staff_note = %s")
                    update_values.append(staff_note_value)
                
                if appointment_data.customer_note is not None:
                    customer_note_value = appointment_data.customer_note.strip() if appointment_data.customer_note and appointment_data.customer_note.strip() else None
                    update_fields.append("customer_note = %s")
                    update_values.append(customer_note_value)
                
                if appointment_data.status is not None:
                    # Eğer status "completed" olarak değiştiriliyorsa, transaction kontrolü yap
                    # Mevcut status'ü kontrol et - eğer zaten completed ise kontrol yapma
                    await cursor.execute(
                        "SELECT status FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
                        (appointment_id, business_id)
                    )
                    current_appointment = await cursor.fetchone()
                    current_status = current_appointment['status'] if current_appointment else None
                    
                    if appointment_data.status == 'completed' and current_status != 'completed':
                        # Status completed olarak değiştiriliyor, transaction kontrolü yap
                        await cursor.execute(
                            "SELECT id FROM transactions WHERE appointment_id = %s AND business_id = %s LIMIT 1",
                            (appointment_id, business_id)
                        )
                        transaction = await cursor.fetchone()
                        if not transaction:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Cannot mark appointment as completed without a transaction. Please add payment details first."
                            )
                    update_fields.append("status = %s")
                    update_values.append(appointment_data.status)
                
                if update_fields:
                    update_fields.append("updated_at = CURRENT_TIMESTAMP")
                    update_values.append(appointment_id)
                    update_values.append(business_id)
                    
                    update_query = f"UPDATE appointments SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                    await cursor.execute(update_query, tuple(update_values))
                
                # Service IDs güncelleniyorsa appointment_services'i güncelle
                if appointment_data.service_ids is not None:
                    # Mevcut services'i sil
                    await cursor.execute(
                        "DELETE FROM appointment_services WHERE appointment_id = %s",
                        (appointment_id,)
                    )
                    
                    # Yeni services'i ekle
                    for service in services:
                        await cursor.execute(
                            "INSERT INTO appointment_services (appointment_id, service_id, price) VALUES (%s, %s, %s)",
                            (appointment_id, service['id'], service['price'])
                        )
                
                await conn.commit()
            
            # Commit sonrası SELECT (tenant-safe)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """
                    SELECT 
                        a.id, a.business_id, a.customer_id, a.staff_id, 
                        a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                        a.created_at, a.updated_at,
                        c.full_name AS customer_full_name,
                        s.full_name AS staff_full_name
                    FROM appointments a
                    LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                    WHERE a.id = %s AND a.business_id = %s
                    LIMIT 1
                    """,
                    (business_id, business_id, appointment_id, business_id)
                )
                appointment = await cursor.fetchone()
                
                if not appointment:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve updated appointment"
                    )
                
                # Services bilgilerini çek (LEFT JOIN kullanarak services olmasa bile appointment dönsün)
                await cursor.execute(
                    """
                    SELECT 
                        aps.service_id,
                        s.name,
                        s.duration_minutes,
                        aps.price,
                        aps.created_at
                    FROM appointments a
                    LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                    LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id = %s
                    ORDER BY aps.created_at
                    """,
                    (business_id, appointment_id)
                )
                services_data = await cursor.fetchall()
                
                # NULL service_id'leri filtrele
                appointment['services'] = [
                    {
                        'service_id': s['service_id'],
                        'name': s['name'],
                        'duration_minutes': s['duration_minutes'],
                        'price': s['price'],
                        'created_at': s['created_at']
                    }
                    for s in services_data if s['service_id'] is not None
                ]
                
                # Transaction bilgisini çek (eğer varsa) - LEFT JOIN ile tek query'de
                try:
                    await cursor.execute(
                        """
                        SELECT 
                            t.id, t.business_id, t.appointment_id, t.customer_id, 
                            t.amount, t.payment_method, t.status, t.transaction_date, t.created_at
                        FROM appointments a
                        LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = a.business_id
                        WHERE a.id = %s AND a.business_id = %s
                        LIMIT 1
                        """,
                        (appointment_id, business_id)
                    )
                    result = await cursor.fetchone()
                    
                    if result and result.get('id') is not None:  # Transaction exists (t.id is not NULL)
                        appointment['transaction'] = {
                            'id': result['id'],
                            'amount': float(result['amount']),
                            'payment_method': result['payment_method'],
                            'status': result['status'],
                            'transaction_date': result['transaction_date'].isoformat() if result['transaction_date'] else None,
                            'created_at': result['created_at'].isoformat() if result['created_at'] else None
                        }
                    else:
                        appointment['transaction'] = None
                except Exception as e:
                    # If transaction query fails, set transaction to None (don't break the appointment response)
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Failed to fetch transaction for appointment {appointment_id}: {str(e)}")
                    appointment['transaction'] = None
            
            return appointment
            
        except HTTPException:
            await conn.rollback()
            raise
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update appointment: {str(e)}"
            )

@router.patch("/{appointment_id}/status", response_model=AppointmentResponse, summary="Update appointment status", description="Update only the status of an appointment (cancel, complete, etc.)")
async def update_appointment_status(
    appointment_id: int,
    status_data: AppointmentStatusUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Randevu durumunu günceller (iptal, tamamla, vb.).
    """
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Staff role kontrolü - staff sadece kendi appointmentlarını güncelleyebilir
    user_role = current_user.get("role")
    user_staff_id = None
    if user_role == "staff":
        user_staff_id = current_user.get("staff_id")
        if user_staff_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff user must have a linked staff profile"
            )
    
    # Use get_connection() context manager for connection with ping check
    async with get_connection() as conn:
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Mevcut randevuyu kontrol et (tenant-safe)
                where_conditions = ["id = %s", "business_id = %s"]
                query_params = [appointment_id, business_id]
                
                # Staff için staff_id kontrolü ekle
                if user_role == "staff" and user_staff_id is not None:
                    where_conditions.append("staff_id = %s")
                    query_params.append(user_staff_id)
                
                where_clause = " AND ".join(where_conditions)
                
                await cursor.execute(
                    f"SELECT id FROM appointments WHERE {where_clause} LIMIT 1",
                    tuple(query_params)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Appointment not found"
                    )
                
                # Status'u güncelle
                update_where_conditions = ["id = %s", "business_id = %s"]
                update_query_params = [appointment_id, business_id]
                
                # Staff için staff_id kontrolü ekle
                if user_role == "staff" and user_staff_id is not None:
                    update_where_conditions.append("staff_id = %s")
                    update_query_params.append(user_staff_id)
                
                update_where_clause = " AND ".join(update_where_conditions)
                
                await cursor.execute(
                    f"UPDATE appointments SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE {update_where_clause}",
                    (status_data.status, *update_query_params)
                )
                
                await conn.commit()
            
            # Commit sonrası SELECT (tenant-safe)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """
                    SELECT 
                        a.id, a.business_id, a.customer_id, a.staff_id, 
                        a.appointment_date, a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, 
                        a.created_at, a.updated_at,
                        c.full_name AS customer_full_name,
                        s.full_name AS staff_full_name
                    FROM appointments a
                    LEFT JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    LEFT JOIN staff s ON a.staff_id = s.id AND s.business_id = %s
                    WHERE a.id = %s AND a.business_id = %s
                    LIMIT 1
                    """,
                    (business_id, business_id, appointment_id, business_id)
                )
                appointment = await cursor.fetchone()
                
                if not appointment:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve updated appointment"
                    )
                
                # Services bilgilerini çek (LEFT JOIN kullanarak services olmasa bile appointment dönsün)
                await cursor.execute(
                    """
                    SELECT 
                        aps.service_id,
                        s.name,
                        s.duration_minutes,
                        aps.price,
                        aps.created_at
                    FROM appointments a
                    LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                    LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id = %s
                    ORDER BY aps.created_at
                    """,
                    (business_id, appointment_id)
                )
                services_data = await cursor.fetchall()
                
                # NULL service_id'leri filtrele
                # NULL service_id'leri filtrele
                appointment['services'] = [
                    {
                        'service_id': s['service_id'],
                        'name': s['name'],
                        'duration_minutes': s['duration_minutes'],
                        'price': s['price'],
                        'created_at': s['created_at']
                    }
                    for s in services_data if s['service_id'] is not None
                ]
            
            return appointment
            
        except HTTPException:
            await conn.rollback()
            raise
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update appointment status: {str(e)}"
            )

@router.post("/{appointment_id}/approve", response_model=AppointmentResponse, summary="Approve pending appointment", description="Approve a pending appointment request (change status from 'pending' to 'scheduled')")
async def approve_appointment(
    appointment_id: int,
    admin_note: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Approve a pending appointment request"""
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
                    # Check if appointment exists and is pending
                    await cursor.execute(
                        "SELECT id, status FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
                        (appointment_id, business_id)
                    )
                    appointment = await cursor.fetchone()
                    
                    if not appointment:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Appointment not found"
                        )
                    
                    if appointment['status'] != 'pending':
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Appointment status is '{appointment['status']}', not 'pending'. Only pending appointments can be approved."
                        )
                    
                    # Update status to 'scheduled'
                    update_fields = ["status = 'scheduled'"]
                    update_values = []
                    
                    if admin_note:
                        update_fields.append("admin_note = %s")
                        update_values.append(admin_note)
                    
                    update_fields.append("updated_at = CURRENT_TIMESTAMP")
                    update_values.append(appointment_id)
                    update_values.append(business_id)
                    
                    update_query = f"UPDATE appointments SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                    await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
                
                # Fetch updated appointment (reuse existing get_appointment logic)
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """SELECT a.id, a.business_id, a.customer_id, a.staff_id, a.appointment_date, 
                        a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, a.created_at, a.updated_at,
                        c.full_name as customer_full_name, c.email as customer_email, c.phone as customer_phone,
                        s.full_name as staff_full_name, s.email as staff_email, s.phone as staff_phone
                        FROM appointments a
                        LEFT JOIN customers c ON c.id = a.customer_id AND c.business_id = a.business_id
                        LEFT JOIN staff s ON s.id = a.staff_id AND s.business_id = a.business_id
                        WHERE a.business_id = %s AND a.id = %s LIMIT 1""",
                        (business_id, appointment_id)
                    )
                    appointment = await cursor.fetchone()
                    
                    if not appointment:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve updated appointment"
                        )
                    
                    # Fetch services
                    await cursor.execute(
                        """
                        SELECT 
                            aps.service_id,
                            s.name,
                            s.duration_minutes,
                            aps.price,
                            aps.created_at
                        FROM appointments a
                        LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                        LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                        WHERE a.business_id = %s AND a.id = %s
                        ORDER BY aps.created_at
                        """,
                        (business_id, appointment_id)
                    )
                    services_data = await cursor.fetchall()
                    
                    appointment['services'] = [
                        {
                            'service_id': s['service_id'],
                            'name': s['name'],
                            'duration_minutes': s['duration_minutes'],
                            'price': s['price'],
                            'created_at': s['created_at']
                        }
                        for s in services_data if s['service_id'] is not None
                    ]
                    
                    # Fetch transaction if exists
                    await cursor.execute(
                        """SELECT id, amount, payment_method, status, transaction_date
                        FROM transactions WHERE appointment_id = %s AND business_id = %s LIMIT 1""",
                        (appointment_id, business_id)
                    )
                    transaction = await cursor.fetchone()
                    appointment['transaction'] = transaction
                
                return appointment
                
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error approving appointment")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to approve appointment: {str(e)}"
                )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.post("/{appointment_id}/reject", response_model=AppointmentResponse, summary="Reject pending appointment", description="Reject a pending appointment request (change status to 'cancelled' with note)")
async def reject_appointment(
    appointment_id: int,
    admin_note: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Reject a pending appointment request"""
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
                    # Check if appointment exists and is pending
                    await cursor.execute(
                        "SELECT id, status FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
                        (appointment_id, business_id)
                    )
                    appointment = await cursor.fetchone()
                    
                    if not appointment:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Appointment not found"
                        )
                    
                    if appointment['status'] != 'pending':
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Appointment status is '{appointment['status']}', not 'pending'. Only pending appointments can be rejected."
                        )
                    
                    # Update status to 'rejected' and add rejection note
                    rejection_note = admin_note or "Rejected"
                    update_fields = ["status = 'rejected'"]
                    update_values = []
                    
                    if admin_note:
                        update_fields.append("admin_note = %s")
                        update_values.append(rejection_note)
                    else:
                        update_fields.append("admin_note = %s")
                        update_values.append(rejection_note)
                    
                    update_fields.append("updated_at = CURRENT_TIMESTAMP")
                    update_values.append(appointment_id)
                    update_values.append(business_id)
                    
                    update_query = f"UPDATE appointments SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                    await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
                
                # Fetch updated appointment
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """SELECT a.id, a.business_id, a.customer_id, a.staff_id, a.appointment_date, 
                        a.status, a.notes, a.admin_note, a.staff_note, a.customer_note, a.created_at, a.updated_at,
                        c.full_name as customer_full_name, c.email as customer_email, c.phone as customer_phone,
                        s.full_name as staff_full_name, s.email as staff_email, s.phone as staff_phone
                        FROM appointments a
                        LEFT JOIN customers c ON c.id = a.customer_id AND c.business_id = a.business_id
                        LEFT JOIN staff s ON s.id = a.staff_id AND s.business_id = a.business_id
                        WHERE a.business_id = %s AND a.id = %s LIMIT 1""",
                        (business_id, appointment_id)
                    )
                    appointment = await cursor.fetchone()
                    
                    if not appointment:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve updated appointment"
                        )
                    
                    # Fetch services
                    await cursor.execute(
                        """
                        SELECT 
                            aps.service_id,
                            s.name,
                            s.duration_minutes,
                            aps.price,
                            aps.created_at
                        FROM appointments a
                        LEFT JOIN appointment_services aps ON aps.appointment_id = a.id
                        LEFT JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                        WHERE a.business_id = %s AND a.id = %s
                        ORDER BY aps.created_at
                        """,
                        (business_id, appointment_id)
                    )
                    services_data = await cursor.fetchall()
                    
                    appointment['services'] = [
                        {
                            'service_id': s['service_id'],
                            'name': s['name'],
                            'duration_minutes': s['duration_minutes'],
                            'price': s['price'],
                            'created_at': s['created_at']
                        }
                        for s in services_data if s['service_id'] is not None
                    ]
                    
                    # Fetch transaction if exists
                    await cursor.execute(
                        """SELECT id, amount, payment_method, status, transaction_date
                        FROM transactions WHERE appointment_id = %s AND business_id = %s LIMIT 1""",
                        (appointment_id, business_id)
                    )
                    transaction = await cursor.fetchone()
                    appointment['transaction'] = transaction
                
                return appointment
                
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                logger.exception("Error rejecting appointment")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to reject appointment: {str(e)}"
                )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

