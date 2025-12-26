from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies import get_current_user, require_not_staff
from app.db import get_db
from app.models.schemas import ServiceCreate, ServiceUpdate, ServiceResponse, TopSellingServiceResponse
from typing import List
from decimal import Decimal
import aiomysql

# Güvenli pymysql import - IntegrityError tuple pattern
try:
    import pymysql.err
    IntegrityErrors = (pymysql.err.IntegrityError,)
except Exception:
    IntegrityErrors = ()

router = APIRouter()

@router.post("/", response_model=ServiceResponse, summary="Create service", description="Create a new service for the authenticated business")
async def create_service(
    service_data: ServiceCreate,
    current_user: dict = Depends(get_current_user)
):
    # Staff cannot create services
    require_not_staff(current_user)
    
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # DB pool kontrolü (deterministik 503)
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    # Defensive: pool None ise AttributeError önle
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        service_id = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Service oluştur
                await cursor.execute(
                    "INSERT INTO services (business_id, name, description, duration_minutes, price, is_active) VALUES (%s, %s, %s, %s, %s, %s)",
                    (business_id, service_data.name, service_data.description, service_data.duration_minutes, service_data.price, service_data.is_active)
                )
                service_id = cursor.lastrowid
            
            await conn.commit()
        except HTTPException:
            # Commit öncesi HTTPException (rollback gerekli)
            await conn.rollback()
            raise
        except IntegrityErrors as e:
            # IntegrityError ayrı except bloğu (409)
            await conn.rollback()
            # Deterministik duplicate detection: error_code 1062 kontrolü
            error_code = e.args[0] if e.args else None
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                error_code = None
            
            if error_code == 1062:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Service already exists"
                )
            else:
                # Diğer IntegrityError'lar (FK vb) => 400
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid service data"
                )
        except Exception as e:
            # MySQL duplicate fallback kontrolü (driver-agnostic)
            await conn.rollback()
            
            error_code = e.args[0] if e.args else None
            error_msg = str(e).lower()
            
            # Deterministik: önce error_code kontrolü (1062 = duplicate key)
            try:
                error_code = int(error_code)
            except (TypeError, ValueError):
                error_code = None
            
            # Primary: error_code 1062 (MySQL duplicate key)
            # Fallback: string heuristic (sadece error_code yoksa)
            is_duplicate = (
                error_code == 1062 or
                (error_code is None and ('duplicate entry' in error_msg or 'duplicate key' in error_msg))
            )
            
            if is_duplicate:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Service already exists"
                )
            
            # Diğer hatalar
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create service"
            )
        
        # Commit sonrası SELECT (tenant-safe, rollback yok)
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                "SELECT id, business_id, name, description, duration_minutes, price, is_active, created_at, updated_at FROM services WHERE id = %s AND business_id = %s LIMIT 1",
                (service_id, business_id)
            )
            service = await cursor.fetchone()
            
            if not service:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve created service"
                )
            
            return service

@router.get("/", response_model=List[ServiceResponse], summary="List services", description="Get all services for the authenticated business")
async def list_services(
    current_user: dict = Depends(get_current_user)
):
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
                "SELECT id, business_id, name, description, duration_minutes, price, is_active, created_at, updated_at FROM services WHERE business_id = %s ORDER BY created_at DESC",
                (business_id,)
            )
            services = await cursor.fetchall()
            return services

@router.get("/top-selling", response_model=List[TopSellingServiceResponse], summary="Get top-selling services", description="Get top-selling services with booking count and total revenue")
async def get_top_selling_services(
    current_user: dict = Depends(get_current_user)
):
    """
    Top 10 en çok satılan hizmet ve gelir raporu getirir.
    
    Özellikler:
    - Sadece 'completed' (tamamlanmış) randevulardaki servisler dikkate alınır.
    - 0 satışlı servisler de dahil edilir (booking_count=0, total_revenue=0), 
      ancak LIMIT 10 nedeniyle sıralama sonucunda görünmeyebilirler.
    - booking_count: Tamamlanmış randevu sayısı (DISTINCT appointment_id). 
      "Units sold" değil, "completed appointment count" olarak düşünülmelidir.
    - total_revenue: Toplam gelir (aynı appointment'ta aynı service birden fazla kez 
      appointment_services'te görünürse revenue artar, booking_count artmaz).
      Bu bilinçli bir tasarım kararıdır (quantity/tekrar desteği).
    
    Tenant İzolasyonu:
    - Cross-tenant veri tutarsızlığı durumunda (yanlış appointment'a bağlı 
      appointment_services satırları) JOIN koşulları (a.business_id = %s) nedeniyle 
      bu satırlar metriklere dahil edilmez (tenant-safe, performans etkisi minimal).
    """
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # DB pool kontrolü (deterministik 503)
    try:
        db_pool = await get_db()
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    # Defensive: pool None ise AttributeError önle
    if db_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # En çok satılan hizmetler (tenant-safe, completed status)
            # LEFT JOIN kullanarak 0 satışlı servisler de dönsün (sıralama ile en alta düşerler)
            # 
            # Tenant izolasyonu:
            # - services.business_id = %s (WHERE clause)
            # - appointments.business_id = %s (JOIN ON clause) -> cross-tenant appointment_services satırları filtrelenir
            #
            # Status filtresi: Metrik seviyesinde (CASE WHEN) uygulanır.
            # Sebep: LEFT JOIN ile 0 satışlı servisler de dönmeli; INNER JOIN kullanırsak kaybolurlar.
            #
            # booking_count: COUNT(DISTINCT a.id) -> tamamlanmış randevu sayısı
            # total_revenue: SUM(aps.price) -> toplam gelir
            # Not: Aynı appointment'ta aynı service birden fazla kez appointment_services'te 
            #      görünürse (schema'da UNIQUE constraint yok), revenue artar ama booking_count artmaz.
            #      Bu bilinçli bir tasarım kararıdır (quantity/tekrar desteği).
            await cursor.execute(
                """
                SELECT 
                    s.id, 
                    s.name, 
                    COUNT(DISTINCT CASE WHEN a.status = 'completed' THEN a.id ELSE NULL END) as booking_count, 
                    COALESCE(SUM(CASE WHEN a.status = 'completed' THEN aps.price ELSE 0 END), 0) as total_revenue
                FROM services s
                LEFT JOIN appointment_services aps ON s.id = aps.service_id
                LEFT JOIN appointments a ON aps.appointment_id = a.id 
                    AND a.business_id = %s
                WHERE s.business_id = %s
                GROUP BY s.id, s.name
                ORDER BY booking_count DESC, total_revenue DESC
                LIMIT 10
                """,
                (business_id, business_id)
            )
            results = await cursor.fetchall()
            
            # Decimal normalization: MySQL'den string gelebilir, Decimal'a çevir
            # (response_model Pydantic validation için gerekli)
            # Not: Bu dönüşüm güvenlidir (0 ise 0, decimal hassasiyet korunur)
            for result in results:
                if result.get("total_revenue") is not None:
                    if not isinstance(result["total_revenue"], Decimal):
                        result["total_revenue"] = Decimal(str(result["total_revenue"]))
                else:
                    result["total_revenue"] = Decimal('0')
            
            # Pydantic response_model kullanarak serialization
            # TopSellingServiceResponse (BaseResponseModel'den türer) otomatik olarak
            # Decimal'ı string'e çevirecek (customer history total_spent ile tutarlı)
            return [TopSellingServiceResponse(**result) for result in results]

@router.get("/{service_id}", response_model=ServiceResponse, summary="Get service", description="Get a single service by ID")
async def get_service(
    service_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Tek bir hizmeti ID ile getirir.
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
                "SELECT id, business_id, name, description, duration_minutes, price, is_active, created_at, updated_at FROM services WHERE id = %s AND business_id = %s LIMIT 1",
                (service_id, business_id)
            )
            service = await cursor.fetchone()
            
            if not service:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Service not found"
                )
            
            return service

@router.put("/{service_id}", response_model=ServiceResponse, summary="Update service", description="Update an existing service")
async def update_service(
    service_id: int,
    service_data: ServiceUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Mevcut hizmeti günceller.
    """
    # Staff cannot update services
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
        service = None
        try:
            await conn.begin()
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Mevcut hizmeti kontrol et (tenant-safe)
                await cursor.execute(
                    "SELECT id FROM services WHERE id = %s AND business_id = %s LIMIT 1",
                    (service_id, business_id)
                )
                if not await cursor.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Service not found"
                    )
                
                # Güncellenecek alanları belirle
                update_fields = []
                update_values = []
                
                if service_data.name is not None:
                    update_fields.append("name = %s")
                    update_values.append(service_data.name)
                if service_data.description is not None:
                    update_fields.append("description = %s")
                    update_values.append(service_data.description)
                if service_data.duration_minutes is not None:
                    update_fields.append("duration_minutes = %s")
                    update_values.append(service_data.duration_minutes)
                if service_data.price is not None:
                    update_fields.append("price = %s")
                    update_values.append(service_data.price)
                if service_data.is_active is not None:
                    update_fields.append("is_active = %s")
                    update_values.append(service_data.is_active)
                
                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )
                
                # UPDATE query
                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_values.append(service_id)
                update_values.append(business_id)
                
                update_query = f"UPDATE services SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
            
            # Commit sonrası SELECT (tenant-safe)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT id, business_id, name, description, duration_minutes, price, is_active, created_at, updated_at FROM services WHERE id = %s AND business_id = %s LIMIT 1",
                    (service_id, business_id)
                )
                service = await cursor.fetchone()
                
                if not service:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve updated service"
                    )
            
            return service
            
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
                    detail="Service already exists"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid service data"
                )
        except Exception as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update service: {str(e)}"
            )

