from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from app.dependencies import get_current_user, require_not_staff
from app.db import get_db, get_connection
from app.models.schemas import CustomerCreate, CustomerUpdate, CustomerResponse, CustomerHistoryResponse
from typing import List
from decimal import Decimal
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

@router.post("/", response_model=CustomerResponse, summary="Create customer", description="Create a new customer for the authenticated business")
async def create_customer(
    customer_data: CustomerCreate,
    current_user: dict = Depends(get_current_user)
):
    # Staff cannot create customers
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
        customer_id = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Customer oluştur
                await cursor.execute(
                    "INSERT INTO customers (business_id, email, phone, full_name) VALUES (%s, %s, %s, %s)",
                    (business_id, customer_data.email, customer_data.phone, customer_data.full_name)
                )
                customer_id = cursor.lastrowid
            
            await conn.commit()
        except HTTPException:
            # Commit öncesi HTTPException (rollback gerekli)
            await conn.rollback()
            raise
        except IntegrityErrors as e:
            # IntegrityError ayrı except bloğu (409)
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Customer with this email already exists"
            )
        except Exception as e:
            # MySQL duplicate fallback kontrolü
            await conn.rollback()
            
            error_msg = str(e).lower()
            error_code = e.args[0] if e.args else None
            
            # MySQL duplicate key error code 1062 veya "Duplicate entry" mesajı
            is_duplicate = (
                error_code == 1062 or
                'duplicate entry' in error_msg or
                'duplicate key' in error_msg
            )
            
            if is_duplicate:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Customer with this email already exists"
                )
            
            # Diğer hatalar
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create customer"
            )
        
        # Commit sonrası SELECT (tenant-safe, rollback yok)
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, email, phone, full_name, created_at, updated_at FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                (customer_id, business_id)
            )
            customer = await cursor.fetchone()
            
            if not customer:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created customer"
                )
            
            return customer

@router.get("/", response_model=List[CustomerResponse], summary="List customers", description="Get all customers for the authenticated business")
async def list_customers(
    request: Request,
    current_user: dict = Depends(get_current_user),
    search: str = Query(None, description="Search by name or email"),
    name: str = Query(None, description="Filter by name (partial match)"),
    email: str = Query(None, description="Filter by email (partial match)"),
    phone: str = Query(None, description="Filter by phone (partial match)")
):
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # ========================================================================
    # STEP 0: Endpoint path doğrulama
    # ========================================================================
    logger.info("=" * 80)
    logger.info("STEP 0: ENDPOINT PATH VERIFICATION")
    logger.info("=" * 80)
    logger.info(f"Request URL (full): {request.url}")
    logger.info(f"Request URL (path only): {request.url.path}")
    expected_path = "/api/customers"
    if request.url.path != expected_path and request.url.path != f"{expected_path}/":
        logger.warning(f"WARNING: Request path '{request.url.path}' doesn't match expected '{expected_path}' or '{expected_path}/'")
    else:
        logger.info(f"✓ Endpoint path matches: {request.url.path}")
    logger.info("=" * 80)
    
    # ========================================================================
    # STEP 1: Query string backend'e geliyor mu? KESINLESTIR
    # ========================================================================
    logger.info("=" * 80)
    logger.info("STEP 1: QUERY STRING VERIFICATION")
    logger.info("=" * 80)
    logger.info(f"Request URL (query string): {request.url.query}")
    logger.info(f"Request URL (query string length): {len(request.url.query)}")
    logger.info(f"Request URL (query string is empty?): {not request.url.query}")
    
    # Parse query string manually to verify
    if request.url.query:
        from urllib.parse import parse_qs
        parsed_query = parse_qs(request.url.query)
        logger.info(f"Parsed query string (parse_qs): {parsed_query}")
        for key, values in parsed_query.items():
            logger.info(f"  Query param '{key}': {values} (first value: {values[0] if values else None})")
    else:
        logger.warning("WARNING: Query string is EMPTY!")
    logger.info("=" * 80)
    
    # ========================================================================
    # STEP 2: Parametre isimleri uyuşuyor mu? DOĞRULA
    # ========================================================================
    logger.info("=" * 80)
    logger.info("STEP 2: RAW PARAMETERS RECEIVED")
    logger.info("=" * 80)
    
    # CRITICAL FIX: Get parameters directly from request.query_params first
    # FastAPI Query() parameters might not work correctly with trailing slashes or redirects
    # Use request.query_params as primary source, FastAPI parsed values as fallback
    query_params_dict = dict(request.query_params)
    logger.info(f"request.query_params (dict): {query_params_dict}")
    
    # Get from request.query_params first (most reliable)
    phone_from_query = query_params_dict.get('phone')
    name_from_query = query_params_dict.get('name')
    email_from_query = query_params_dict.get('email')
    search_from_query = query_params_dict.get('search')
    
    logger.info(f"From request.query_params:")
    logger.info(f"  phone: {repr(phone_from_query)}")
    logger.info(f"  name: {repr(name_from_query)}")
    logger.info(f"  email: {repr(email_from_query)}")
    logger.info(f"  search: {repr(search_from_query)}")
    
    logger.info(f"From FastAPI Query() parameters:")
    logger.info(f"  search: {repr(search)} (type: {type(search).__name__})")
    logger.info(f"  name: {repr(name)} (type: {type(name).__name__})")
    logger.info(f"  email: {repr(email)} (type: {type(email).__name__})")
    logger.info(f"  phone: {repr(phone)} (type: {type(phone).__name__})")
    
    # Use request.query_params values if available, otherwise use FastAPI parsed values
    # This ensures we always get the parameters even if FastAPI parsing fails
    # Note: request.query_params.get() returns None if param doesn't exist, or string if exists
    if phone_from_query is not None:
        phone = phone_from_query
        logger.info(f"  -> Using phone from request.query_params: {repr(phone)}")
    elif phone is not None:
        logger.info(f"  -> Using phone from FastAPI Query(): {repr(phone)}")
    else:
        logger.info(f"  -> phone is None (not in query params)")
    
    if name_from_query is not None:
        name = name_from_query
        logger.info(f"  -> Using name from request.query_params: {repr(name)}")
    elif name is not None:
        logger.info(f"  -> Using name from FastAPI Query(): {repr(name)}")
    else:
        logger.info(f"  -> name is None (not in query params)")
    
    if email_from_query is not None:
        email = email_from_query
        logger.info(f"  -> Using email from request.query_params: {repr(email)}")
    elif email is not None:
        logger.info(f"  -> Using email from FastAPI Query(): {repr(email)}")
    else:
        logger.info(f"  -> email is None (not in query params)")
    
    if search_from_query is not None:
        search = search_from_query
        logger.info(f"  -> Using search from request.query_params: {repr(search)}")
    elif search is not None:
        logger.info(f"  -> Using search from FastAPI Query(): {repr(search)}")
    else:
        logger.info(f"  -> search is None (not in query params)")
    
    logger.info("FINAL VALUES BEFORE NORMALIZATION:")
    logger.info(f"  search: {repr(search)}")
    logger.info(f"  name: {repr(name)}")
    logger.info(f"  email: {repr(email)}")
    logger.info(f"  phone: {repr(phone)}")
    
    logger.info("=" * 80)
    
    try:
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # ========================================================================
                # STEP 3: Normalization'ın her şeyi None yapmadığını kanıtla
                # ========================================================================
                logger.info("=" * 80)
                logger.info("STEP 3: NORMALIZATION")
                logger.info("=" * 80)
                logger.info("BEFORE NORMALIZATION:")
                logger.info(f"  search: {repr(search)} (type: {type(search).__name__})")
                logger.info(f"  name: {repr(name)} (type: {type(name).__name__})")
                logger.info(f"  email: {repr(email)} (type: {type(email).__name__})")
                logger.info(f"  phone: {repr(phone)} (type: {type(phone).__name__})")
                
                # Store original values for comparison
                original_values = {'search': search, 'name': name, 'email': email, 'phone': phone}
                
                # Normalize: strip if string and not empty, else None
                if search and isinstance(search, str):
                    search = search.strip() if search.strip() else None
                else:
                    search = None
                    
                if name and isinstance(name, str):
                    name = name.strip() if name.strip() else None
                else:
                    name = None
                    
                if email and isinstance(email, str):
                    email = email.strip() if email.strip() else None
                else:
                    email = None
                    
                if phone and isinstance(phone, str):
                    phone = phone.strip() if phone.strip() else None
                else:
                    phone = None
                
                logger.info("AFTER NORMALIZATION:")
                logger.info(f"  search: {repr(search)}")
                logger.info(f"  name: {repr(name)}")
                logger.info(f"  email: {repr(email)}")
                logger.info(f"  phone: {repr(phone)}")
                
                # Check if normalization turned non-empty values into None
                for key, original in original_values.items():
                    normalized = {'search': search, 'name': name, 'email': email, 'phone': phone}[key]
                    if original and isinstance(original, str) and original.strip() and normalized is None:
                        logger.warning(f"WARNING: '{key}' was non-empty string but normalized to None!")
                    elif original and normalized != original:
                        logger.info(f"  '{key}' normalized: {repr(original)} -> {repr(normalized)}")
                logger.info("=" * 80)
                
                # Build WHERE conditions dynamically
                where_conditions = ["business_id = %s"]
                query_params = [business_id]
                
                # Legacy search parameter (for backward compatibility)
                if search:
                    where_conditions.append("(full_name LIKE %s OR email LIKE %s)")
                    query_params.extend([f"%{search}%", f"%{search}%"])
                    logger.info(f"  -> Added search filter: {search}")
                else:
                    # Individual filters
                    if name:
                        where_conditions.append("full_name LIKE %s")
                        query_params.append(f"%{name}%")
                        logger.info(f"  -> Added name filter: {name}")
                    if email:
                        where_conditions.append("email LIKE %s")
                        query_params.append(f"%{email}%")
                        logger.info(f"  -> Added email filter: {email}")
                    if phone:
                        where_conditions.append("phone LIKE %s")
                        query_params.append(f"%{phone}%")
                        logger.info(f"  -> Added phone filter: {phone}")
                
                where_clause = " AND ".join(where_conditions)
                
                # ========================================================================
                # STEP 4: DB tarafında gerçekten filtreli sonuç dönüyor mu?
                # ========================================================================
                logger.info("=" * 80)
                logger.info("STEP 4: SQL QUERY CONSTRUCTION")
                logger.info("=" * 80)
                logger.info(f"WHERE conditions count: {len(where_conditions)}")
                logger.info(f"WHERE conditions: {where_conditions}")
                logger.info(f"WHERE clause: {where_clause}")
                logger.info(f"Query params count: {len(query_params)}")
                logger.info(f"Query params: {query_params}")
                logger.info(f"Query params types: {[type(p).__name__ for p in query_params]}")
                
                # Check if filters were actually added
                if len(where_conditions) == 1:
                    logger.warning("WARNING: Only business_id filter is present, no user filters applied!")
                else:
                    logger.info(f"Filters applied: {len(where_conditions) - 1} filter(s) in addition to business_id")
                logger.info("=" * 80)
                
                query = f"""
                    SELECT id, business_id, email, phone, full_name, created_at, updated_at 
                    FROM customers 
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                """
                
                logger.info("=" * 80)
                logger.info("FINAL SQL QUERY:")
                logger.info(query)
                logger.info("FINAL QUERY PARAMS (as tuple):")
                logger.info(tuple(query_params))
                logger.info("=" * 80)
                
                await cursor.execute(query, tuple(query_params))
                customers = await cursor.fetchall()
                
                # ========================================================================
                # STEP 5: Result verification
                # ========================================================================
                logger.info("=" * 80)
                logger.info("STEP 5: QUERY RESULT")
                logger.info("=" * 80)
                logger.info(f"Result count: {len(customers)}")
                logger.info(f"Cursor rowcount: {cursor.rowcount}")
                
                if customers:
                    logger.info(f"First customer sample:")
                    first_customer = customers[0]
                    logger.info(f"  ID: {first_customer.get('id')}")
                    logger.info(f"  Name: {first_customer.get('full_name')}")
                    logger.info(f"  Email: {first_customer.get('email')}")
                    logger.info(f"  Phone: {first_customer.get('phone')}")
                    
                    # If filtering by phone, verify first result matches
                    if phone:
                        first_phone = first_customer.get('phone', '')
                        if phone not in first_phone:
                            logger.warning(f"WARNING: Filtered by phone '{phone}' but first result phone '{first_phone}' doesn't contain it!")
                    
                    # If filtering by name, verify first result matches
                    if name:
                        first_name = first_customer.get('full_name', '')
                        if name.lower() not in first_name.lower():
                            logger.warning(f"WARNING: Filtered by name '{name}' but first result name '{first_name}' doesn't contain it!")
                    
                    # If filtering by email, verify first result matches
                    if email:
                        first_email = first_customer.get('email', '')
                        if email.lower() not in first_email.lower():
                            logger.warning(f"WARNING: Filtered by email '{email}' but first result email '{first_email}' doesn't contain it!")
                else:
                    logger.info("No customers found (empty result)")
                logger.info("=" * 80)
                
                return customers
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.get("/{customer_id}/history", response_model=CustomerHistoryResponse, summary="Get customer history", description="Get customer appointment history, total spending, and last appointment details")
async def get_customer_history(
    customer_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Müşteri geçmişi, toplam harcama, son randevu bilgilerini getirir.
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
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Müşteri bilgisi (tenant-safe)
            await cursor.execute(
                "SELECT id, business_id, email, phone, full_name, created_at, updated_at FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                (customer_id, business_id)
            )
            customer = await cursor.fetchone()
            if not customer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found"
                )
            
            # Toplam harcama (tenant-safe) - status='completed' doğru (schema: ENUM('pending', 'completed', 'refunded'))
            await cursor.execute(
                """
                SELECT COALESCE(SUM(amount), 0) as total_spent
                FROM transactions
                WHERE customer_id = %s AND business_id = %s AND status = 'completed'
                """,
                (customer_id, business_id)
            )
            total_spent_result = await cursor.fetchone()
            # Decimal olarak koru (float() yerine)
            total_spent = Decimal(str(total_spent_result["total_spent"])) if total_spent_result and total_spent_result["total_spent"] else Decimal('0')
            
            # Tüm randevular (tenant-safe)
            await cursor.execute(
                """
                SELECT 
                    a.id, a.business_id, a.customer_id, a.staff_id, 
                    a.appointment_date, a.status, a.notes, 
                    a.created_at, a.updated_at
                FROM appointments a
                WHERE a.customer_id = %s AND a.business_id = %s
                ORDER BY a.appointment_date DESC
                """,
                (customer_id, business_id)
            )
            appointments = await cursor.fetchall()
            
            # Services bilgilerini nested liste formatında ekle (N+1 query yok)
            if appointments:
                appointment_ids = [appt['id'] for appt in appointments]
                
                # appointment_ids ile appointment_services + services join'ini tek seferde çek
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
                    INNER JOIN appointment_services aps ON aps.appointment_id = a.id
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
                    WHERE a.business_id = %s AND a.id IN ({placeholders})
                    ORDER BY aps.appointment_id, aps.created_at
                """
                await cursor.execute(services_query, (business_id, *appointment_ids))
                services_data = await cursor.fetchall()
                
                # appointment_id'ye göre grupla
                services_by_appointment = {}
                for service in services_data:
                    appointment_id = service['appointment_id']
                    if appointment_id not in services_by_appointment:
                        services_by_appointment[appointment_id] = []
                    services_by_appointment[appointment_id].append({
                        'service_id': service['service_id'],
                        'name': service['name'],
                        'duration_minutes': service['duration_minutes'],
                        'price': service['price'],
                        'created_at': service['created_at']
                    })
                
                # Her appointment'a services alanı ekle
                for appt in appointments:
                    appointment_id = appt['id']
                    if appointment_id in services_by_appointment:
                        appt['services'] = services_by_appointment[appointment_id]
                    else:
                        appt['services'] = []
            
            # Son randevu: appointments listesinden al (ekstra query yok)
            last_appointment = appointments[0] if appointments else None
            
            return {
                "customer": customer,
                "total_spent": total_spent,
                "last_appointment": last_appointment,
                "appointments": appointments
            }

@router.get("/{customer_id}", response_model=CustomerResponse, summary="Get customer", description="Get a single customer by ID")
async def get_customer(
    customer_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Tek bir müşteriyi ID ile getirir.
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
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, email, phone, full_name, created_at, updated_at FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                (customer_id, business_id)
            )
            customer = await cursor.fetchone()
            
            if not customer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Customer not found"
                )
            
            return customer

@router.put("/{customer_id}", response_model=CustomerResponse, summary="Update customer", description="Update an existing customer")
async def update_customer(
    customer_id: int,
    customer_data: CustomerUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Mevcut müşteriyi günceller.
    """
    # Staff cannot update customers
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
        customer = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Mevcut müşteriyi kontrol et (tenant-safe)
                await cursor.execute(
                    "SELECT id FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                    (customer_id, business_id)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Customer not found"
                    )
                
                # Güncellenecek alanları belirle
                update_fields = []
                update_values = []
                
                if customer_data.full_name is not None:
                    update_fields.append("full_name = %s")
                    update_values.append(customer_data.full_name)
                if customer_data.email is not None:
                    update_fields.append("email = %s")
                    update_values.append(customer_data.email)
                if customer_data.phone is not None:
                    update_fields.append("phone = %s")
                    update_values.append(customer_data.phone)
                
                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )
                
                # UPDATE query
                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_values.append(customer_id)
                update_values.append(business_id)
                
                update_query = f"UPDATE customers SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
            
            # Commit sonrası SELECT (tenant-safe)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT id, business_id, email, phone, full_name, created_at, updated_at FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                    (customer_id, business_id)
                )
                customer = await cursor.fetchone()
                
                if not customer:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve updated customer"
                    )
            
            return customer
            
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
                    detail="Email already exists"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid customer data"
                )
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update customer: {str(e)}"
            )
