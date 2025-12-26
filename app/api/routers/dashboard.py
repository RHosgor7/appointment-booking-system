from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies import get_current_user
from app.db import get_db
from app.models.schemas import BaseResponseModel
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, date
import aiomysql

router = APIRouter()

class TodayStatsResponse(BaseResponseModel):
    today_total: int
    today_completed: int
    today_cancelled: int
    today_revenue: Decimal

class PerformanceStatsResponse(BaseResponseModel):
    period: str  # "7d", "mtd", "30d"
    total: int
    completed: int
    cancelled: int
    revenue: Decimal

class DashboardPerformanceResponse(BaseResponseModel):
    w7: PerformanceStatsResponse
    mtd: PerformanceStatsResponse
    d30: PerformanceStatsResponse

class UpcomingAppointmentResponse(BaseResponseModel):
    id: int
    customer_full_name: str
    appointment_date: datetime
    services: List[str]
    time_range: str

class ServiceCompletionRateResponse(BaseResponseModel):
    service_id: int
    service_name: str
    completed: int
    total: int
    completion_rate: float  # percentage

class ServiceStatisticsItemResponse(BaseResponseModel):
    service_id: int
    service_name: str
    minutes_spent: int  # total duration in minutes
    revenue: Decimal

class ServiceStatisticsResponse(BaseResponseModel):
    services: List[ServiceStatisticsItemResponse]

class RevenueOverviewServiceItemResponse(BaseResponseModel):
    service_id: int
    service_name: str
    minutes_spent: int
    revenue: Decimal
    avg_revenue_per_service: Decimal  # Her servis için ortalama gelir
    appointment_count: int

class RevenueOverviewResponse(BaseResponseModel):
    avg_revenue_all: Decimal
    avg_revenue_change_pct: float  # percentage change from previous period
    services: List[RevenueOverviewServiceItemResponse]  # service revenue data with per-service average

@router.get("/today-stats", response_model=TodayStatsResponse, summary="Get today's statistics", description="Get today's appointment statistics. Staff sees only their appointments, Admin/Owner sees all")
async def get_today_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Bugünün istatistiklerini getirir.
    - Staff: Sadece kendi randevuları
    - Admin/Owner: Tüm randevular
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    # Staff user ama staff tablosunda kayıt yok
                    return {
                        "today_total": 0,
                        "today_completed": 0,
                        "today_cancelled": 0,
                        "today_revenue": Decimal("0.00")
                    }
                staff_id_filter = staff_result['id']
            
            # Bugünün randevularını say
            if staff_id_filter:
                # Staff: Sadece kendi randevuları
                await cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                    FROM appointments
                    WHERE business_id = %s 
                      AND staff_id = %s
                      AND DATE(appointment_date) = CURDATE()
                    """,
                    (business_id, staff_id_filter)
                )
            else:
                # Admin/Owner: Tüm randevular
                await cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                    FROM appointments
                    WHERE business_id = %s
                      AND DATE(appointment_date) = CURDATE()
                    """,
                    (business_id,)
                )
            
            stats = await cursor.fetchone()
            
            # Bugünün gelirini hesapla (completed transactions)
            if staff_id_filter:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.staff_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                      AND t.status = 'completed'
                    """,
                    (business_id, staff_id_filter)
                )
            else:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                      AND t.status = 'completed'
                    """,
                    (business_id,)
                )
            
            revenue_result = await cursor.fetchone()
            revenue = Decimal(str(revenue_result['revenue'])) if revenue_result['revenue'] else Decimal("0.00")
            
            return {
                "today_total": stats['total'] or 0,
                "today_completed": stats['completed'] or 0,
                "today_cancelled": stats['cancelled'] or 0,
                "today_revenue": revenue
            }

@router.get("/performance", response_model=DashboardPerformanceResponse, summary="Get performance statistics", description="Get performance statistics for 7 days, MTD, and 30 days. Staff sees only their data, Admin/Owner sees all")
async def get_performance_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Performans istatistiklerini getirir (7 gün, bu ay, 30 gün).
    - Staff: Sadece kendi verileri
    - Admin/Owner: Tüm veriler
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    # Boş veri döndür
                    empty_stats = PerformanceStatsResponse(
                        period="",
                        total=0,
                        completed=0,
                        cancelled=0,
                        revenue=Decimal("0.00")
                    )
                    return {
                        "w7": empty_stats,
                        "mtd": empty_stats,
                        "d30": empty_stats
                    }
                staff_id_filter = staff_result['id']
            
            def get_period_stats(days: Optional[int] = None, mtd: bool = False):
                """Helper function to get stats for a period"""
                if mtd:
                    date_filter = "MONTH(a.appointment_date) = MONTH(CURDATE()) AND YEAR(a.appointment_date) = YEAR(CURDATE())"
                elif days:
                    date_filter = f"a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)"
                else:
                    date_filter = "1=1"
                
                if staff_id_filter:
                    query = f"""
                        SELECT 
                            COUNT(*) as total,
                            SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) as completed,
                            SUM(CASE WHEN a.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                        FROM appointments a
                        WHERE a.business_id = %s 
                          AND a.staff_id = %s
                          AND {date_filter}
                    """
                    params = (business_id, staff_id_filter)
                else:
                    query = f"""
                        SELECT 
                            COUNT(*) as total,
                            SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) as completed,
                            SUM(CASE WHEN a.status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                        FROM appointments a
                        WHERE a.business_id = %s
                          AND {date_filter}
                    """
                    params = (business_id,)
                
                return query, params
            
            # 7 gün
            query_7d, params_7d = get_period_stats(days=7)
            await cursor.execute(query_7d, params_7d)
            stats_7d = await cursor.fetchone()
            
            # Revenue for 7 days
            if staff_id_filter:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.staff_id = %s
                      AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                      AND t.status = 'completed'
                    """,
                    (business_id, staff_id_filter)
                )
            else:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                      AND t.status = 'completed'
                    """,
                    (business_id,)
                )
            revenue_7d = await cursor.fetchone()
            
            # MTD (Month to Date)
            query_mtd, params_mtd = get_period_stats(mtd=True)
            await cursor.execute(query_mtd, params_mtd)
            stats_mtd = await cursor.fetchone()
            
            # Revenue for MTD
            if staff_id_filter:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.staff_id = %s
                      AND MONTH(a.appointment_date) = MONTH(CURDATE())
                      AND YEAR(a.appointment_date) = YEAR(CURDATE())
                      AND t.status = 'completed'
                    """,
                    (business_id, staff_id_filter)
                )
            else:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND MONTH(a.appointment_date) = MONTH(CURDATE())
                      AND YEAR(a.appointment_date) = YEAR(CURDATE())
                      AND t.status = 'completed'
                    """,
                    (business_id,)
                )
            revenue_mtd = await cursor.fetchone()
            
            # 30 gün
            query_30d, params_30d = get_period_stats(days=30)
            await cursor.execute(query_30d, params_30d)
            stats_30d = await cursor.fetchone()
            
            # Revenue for 30 days
            if staff_id_filter:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.staff_id = %s
                      AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                      AND t.status = 'completed'
                    """,
                    (business_id, staff_id_filter)
                )
            else:
                await cursor.execute(
                    """
                    SELECT COALESCE(SUM(t.amount), 0) as revenue
                    FROM transactions t
                    INNER JOIN appointments a ON t.appointment_id = a.id
                    WHERE t.business_id = %s
                      AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                      AND t.status = 'completed'
                    """,
                    (business_id,)
                )
            revenue_30d = await cursor.fetchone()
            
            return {
                "w7": {
                    "period": "7d",
                    "total": stats_7d['total'] or 0,
                    "completed": stats_7d['completed'] or 0,
                    "cancelled": stats_7d['cancelled'] or 0,
                    "revenue": Decimal(str(revenue_7d['revenue'])) if revenue_7d['revenue'] else Decimal("0.00")
                },
                "mtd": {
                    "period": "mtd",
                    "total": stats_mtd['total'] or 0,
                    "completed": stats_mtd['completed'] or 0,
                    "cancelled": stats_mtd['cancelled'] or 0,
                    "revenue": Decimal(str(revenue_mtd['revenue'])) if revenue_mtd['revenue'] else Decimal("0.00")
                },
                "d30": {
                    "period": "30d",
                    "total": stats_30d['total'] or 0,
                    "completed": stats_30d['completed'] or 0,
                    "cancelled": stats_30d['cancelled'] or 0,
                    "revenue": Decimal(str(revenue_30d['revenue'])) if revenue_30d['revenue'] else Decimal("0.00")
                }
            }

@router.get("/upcoming", response_model=List[UpcomingAppointmentResponse], summary="Get upcoming appointments", description="Get today's upcoming appointments ordered by time. Staff sees only their appointments, Admin/Owner sees all")
async def get_upcoming_appointments(
    current_user: dict = Depends(get_current_user),
    limit: int = 3
):
    """
    Bugünün yaklaşan randevularını getirir (saat sırasına göre).
    - Staff: Sadece kendi randevuları
    - Admin/Owner: Tüm randevular
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    return []
                staff_id_filter = staff_result['id']
            
            # Bugünün randevularını getir (saat sırasına göre)
            if staff_id_filter:
                await cursor.execute(
                    """
                    SELECT 
                        a.id,
                        a.appointment_date,
                        c.full_name AS customer_full_name
                    FROM appointments a
                    INNER JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    WHERE a.business_id = %s
                      AND a.staff_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                      AND a.status = 'scheduled'
                    ORDER BY a.appointment_date ASC
                    LIMIT %s
                    """,
                    (business_id, business_id, staff_id_filter, limit)
                )
            else:
                await cursor.execute(
                    """
                    SELECT 
                        a.id,
                        a.appointment_date,
                        c.full_name AS customer_full_name
                    FROM appointments a
                    INNER JOIN customers c ON a.customer_id = c.id AND c.business_id = %s
                    WHERE a.business_id = %s
                      AND DATE(a.appointment_date) = CURDATE()
                      AND a.status = 'scheduled'
                    ORDER BY a.appointment_date ASC
                    LIMIT %s
                    """,
                    (business_id, business_id, limit)
                )
            
            appointments = await cursor.fetchall()
            
            if not appointments:
                return []
            
            # Her randevu için services bilgilerini çek
            appointment_ids = [appt['id'] for appt in appointments]
            placeholders = ','.join(['%s'] * len(appointment_ids))
            
            await cursor.execute(
                f"""
                SELECT 
                    aps.appointment_id,
                    s.name
                FROM appointment_services aps
                INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                WHERE aps.appointment_id IN ({placeholders})
                ORDER BY aps.appointment_id, aps.created_at
                """,
                (business_id, *appointment_ids)
            )
            services_data = await cursor.fetchall()
            
            # Services'leri appointment'lara ekle
            services_by_appointment = {}
            for service in services_data:
                appointment_id = service['appointment_id']
                if appointment_id not in services_by_appointment:
                    services_by_appointment[appointment_id] = []
                services_by_appointment[appointment_id].append(service['name'])
            
            # Response oluştur
            result = []
            for appt in appointments:
                appointment_id = appt['id']
                appointment_date = appt['appointment_date']
                services = services_by_appointment.get(appointment_id, [])
                
                # Time range hesapla (basit: sadece başlangıç saati)
                time_str = appointment_date.strftime("%H:%M") if isinstance(appointment_date, datetime) else str(appointment_date)
                
                result.append({
                    "id": appointment_id,
                    "customer_full_name": appt['customer_full_name'],
                    "appointment_date": appointment_date,
                    "services": services,
                    "time_range": time_str
                })
            
            return result

@router.get("/service-completion-rates", response_model=List[ServiceCompletionRateResponse], summary="Get service completion rates", description="Get top 5 services by completion rate. Staff sees only their appointments, Admin/Owner sees all")
async def get_service_completion_rates(
    current_user: dict = Depends(get_current_user),
    limit: int = 5
):
    """
    Servis bazlı tamamlanma oranlarını getirir (top 5).
    - Staff: Sadece kendi randevuları
    - Admin/Owner: Tüm randevular
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    return []
                staff_id_filter = staff_result['id']
            
            # Servis bazlı tamamlanma oranlarını hesapla
            if staff_id_filter:
                query = """
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COUNT(CASE WHEN a.status = 'completed' THEN 1 END) as completed,
                        COUNT(*) as total
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    WHERE a.staff_id = %s
                    GROUP BY s.id, s.name
                    HAVING total > 0
                    ORDER BY (completed / total) DESC, total DESC
                    LIMIT %s
                """
                await cursor.execute(query, (business_id, business_id, staff_id_filter, limit))
            else:
                query = """
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COUNT(CASE WHEN a.status = 'completed' THEN 1 END) as completed,
                        COUNT(*) as total
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    GROUP BY s.id, s.name
                    HAVING total > 0
                    ORDER BY (completed / total) DESC, total DESC
                    LIMIT %s
                """
                await cursor.execute(query, (business_id, business_id, limit))
            
            results = await cursor.fetchall()
            
            # Completion rate hesapla
            response = []
            for row in results:
                completion_rate = (row['completed'] / row['total']) * 100 if row['total'] > 0 else 0.0
                response.append({
                    "service_id": row['service_id'],
                    "service_name": row['service_name'],
                    "completed": row['completed'],
                    "total": row['total'],
                    "completion_rate": round(completion_rate, 2)
                })
            
            return response

@router.get("/service-statistics", response_model=ServiceStatisticsResponse, summary="Get service statistics", description="Get service statistics (time spent and revenue) by service. Staff sees only their appointments, Admin/Owner sees all")
async def get_service_statistics(
    current_user: dict = Depends(get_current_user),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Servis bazlı istatistikleri getirir (harcanan süre ve gelir).
    - Staff: Sadece kendi randevuları
    - Admin/Owner: Tüm randevular
    
    start_date ve end_date opsiyonel. Belirtilmezse son 30 gün.
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    return {"services": []}
                staff_id_filter = staff_result['id']
            
            # Tarih filtresi
            if start_date and end_date:
                date_filter = "AND DATE(a.appointment_date) BETWEEN %s AND %s"
                date_params = (start_date, end_date)
            else:
                # Varsayılan: son 30 gün
                date_filter = "AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
                date_params = ()
            
            # Servis bazlı istatistikleri hesapla
            # Her appointment_service kaydı için service duration'ı topla
            if staff_id_filter:
                query = f"""
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COALESCE(SUM(s.duration_minutes), 0) as minutes_spent,
                        COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount ELSE 0 END), 0) as revenue
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.staff_id = %s
                      {date_filter}
                    GROUP BY s.id, s.name
                    ORDER BY revenue DESC, minutes_spent DESC
                """
                params = (business_id, business_id, business_id, staff_id_filter) + date_params
            else:
                query = f"""
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COALESCE(SUM(s.duration_minutes), 0) as minutes_spent,
                        COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount ELSE 0 END), 0) as revenue
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE 1=1
                      {date_filter}
                    GROUP BY s.id, s.name
                    ORDER BY revenue DESC, minutes_spent DESC
                """
                params = (business_id, business_id, business_id) + date_params
            
            await cursor.execute(query, params)
            results = await cursor.fetchall()
            
            # Response oluştur
            services = []
            for row in results:
                services.append({
                    "service_id": row['service_id'],
                    "service_name": row['service_name'],
                    "minutes_spent": int(row['minutes_spent'] or 0),
                    "revenue": Decimal(str(row['revenue'] or 0))
                })
            
            return {"services": services}

@router.get("/revenue-overview", response_model=RevenueOverviewResponse, summary="Get revenue overview", description="Get average revenue and service-based revenue statistics. Staff sees only their data, Admin/Owner sees all")
async def get_revenue_overview(
    current_user: dict = Depends(get_current_user),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Gelir genel bakış verilerini getirir.
    - Ortalama gelir (tüm randevuların ortalaması)
    - Önceki dönemle karşılaştırma (trend yüzdesi)
    - Servis bazında gelir verileri
    
    - Staff: Sadece kendi randevuları
    - Admin/Owner: Tüm randevular
    
    start_date ve end_date opsiyonel. Belirtilmezse son 30 gün.
    """
    business_id = current_user.get("business_id")
    user_id = current_user.get("id")
    user_role = current_user.get("role")
    
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
            # Staff ise, user_id'ye bağlı staff_id bul
            staff_id_filter = None
            if user_role == 'staff':
                await cursor.execute(
                    "SELECT id FROM staff WHERE business_id = %s AND user_id = %s LIMIT 1",
                    (business_id, user_id)
                )
                staff_result = await cursor.fetchone()
                if not staff_result:
                    return {
                        "avg_revenue_all": Decimal("0.00"),
                        "avg_revenue_change_pct": 0.0,
                        "services": []
                    }
                staff_id_filter = staff_result['id']
            
            # Tarih filtresi
            if start_date and end_date:
                date_filter = "AND DATE(a.appointment_date) BETWEEN %s AND %s"
                prev_date_filter = "AND DATE(a.appointment_date) BETWEEN DATE_SUB(%s, INTERVAL DATEDIFF(%s, %s) DAY) AND DATE_SUB(%s, INTERVAL 1 DAY)"
                date_params = (start_date, end_date)
                prev_date_params = (start_date, end_date, start_date, end_date)
            else:
                # Varsayılan: son 30 gün
                date_filter = "AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
                prev_date_filter = "AND a.appointment_date >= DATE_SUB(CURDATE(), INTERVAL 60 DAY) AND a.appointment_date < DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
                date_params = ()
                prev_date_params = ()
            
            # Mevcut dönem: Ortalama gelir hesapla
            if staff_id_filter:
                query_avg = f"""
                    SELECT 
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue
                    FROM appointments a
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.business_id = %s
                      AND a.staff_id = %s
                      {date_filter}
                """
                params_avg = (business_id, business_id, staff_id_filter) + date_params
            else:
                query_avg = f"""
                    SELECT 
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue
                    FROM appointments a
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.business_id = %s
                      {date_filter}
                """
                params_avg = (business_id, business_id) + date_params
            
            await cursor.execute(query_avg, params_avg)
            avg_result = await cursor.fetchone()
            avg_revenue = Decimal(str(avg_result['avg_revenue'] or 0))
            
            # Önceki dönem: Ortalama gelir hesapla (trend için)
            if staff_id_filter:
                query_prev_avg = f"""
                    SELECT 
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue
                    FROM appointments a
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.business_id = %s
                      AND a.staff_id = %s
                      {prev_date_filter}
                """
                params_prev_avg = (business_id, business_id, staff_id_filter) + prev_date_params
            else:
                query_prev_avg = f"""
                    SELECT 
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue
                    FROM appointments a
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.business_id = %s
                      {prev_date_filter}
                """
                params_prev_avg = (business_id, business_id) + prev_date_params
            
            await cursor.execute(query_prev_avg, params_prev_avg)
            prev_avg_result = await cursor.fetchone()
            prev_avg_revenue = Decimal(str(prev_avg_result['avg_revenue'] or 0))
            
            # Trend yüzdesi hesapla
            if prev_avg_revenue > 0:
                change_pct = ((avg_revenue - prev_avg_revenue) / prev_avg_revenue) * 100
            else:
                change_pct = 0.0 if avg_revenue == 0 else 100.0
            
            # Servis bazlı gelir verileri - Her servis için toplam gelir ve ortalama gelir hesapla
            if staff_id_filter:
                query_services = f"""
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COALESCE(SUM(s.duration_minutes), 0) as minutes_spent,
                        COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount ELSE 0 END), 0) as revenue,
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue_per_service,
                        COUNT(DISTINCT CASE WHEN t.status = 'completed' THEN a.id END) as appointment_count
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE a.staff_id = %s
                      {date_filter}
                    GROUP BY s.id, s.name
                    ORDER BY revenue DESC, minutes_spent DESC
                """
                params_services = (business_id, business_id, business_id, staff_id_filter) + date_params
            else:
                query_services = f"""
                    SELECT 
                        s.id as service_id,
                        s.name as service_name,
                        COALESCE(SUM(s.duration_minutes), 0) as minutes_spent,
                        COALESCE(SUM(CASE WHEN t.status = 'completed' THEN t.amount ELSE 0 END), 0) as revenue,
                        COALESCE(AVG(CASE WHEN t.status = 'completed' THEN t.amount END), 0) as avg_revenue_per_service,
                        COUNT(DISTINCT CASE WHEN t.status = 'completed' THEN a.id END) as appointment_count
                    FROM appointment_services aps
                    INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                    INNER JOIN appointments a ON a.id = aps.appointment_id AND a.business_id = %s
                    LEFT JOIN transactions t ON t.appointment_id = a.id AND t.business_id = %s AND t.status = 'completed'
                    WHERE 1=1
                      {date_filter}
                    GROUP BY s.id, s.name
                    ORDER BY revenue DESC, minutes_spent DESC
                """
                params_services = (business_id, business_id, business_id) + date_params
            
            await cursor.execute(query_services, params_services)
            services_results = await cursor.fetchall()
            
            # Response oluştur
            services = []
            for row in services_results:
                services.append({
                    "service_id": row['service_id'],
                    "service_name": row['service_name'],
                    "minutes_spent": int(row['minutes_spent'] or 0),
                    "revenue": Decimal(str(row['revenue'] or 0)),
                    "avg_revenue_per_service": Decimal(str(row['avg_revenue_per_service'] or 0)),
                    "appointment_count": int(row['appointment_count'] or 0)
                })
            
            return {
                "avg_revenue_all": avg_revenue,
                "avg_revenue_change_pct": round(change_pct, 2),
                "services": services
            }

