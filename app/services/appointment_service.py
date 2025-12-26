from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
import aiomysql


def _normalize_datetime_to_utc_aware(dt: datetime) -> datetime:
    """
    Datetime'ı UTC-aware'e normalize eder.
    - Zaten aware ise UTC'ye çevir
    - Naive ise UTC olarak kabul et (timezone bilgisi yok)
    
    Args:
        dt: datetime objesi (aware veya naive)
    
    Returns:
        UTC-aware datetime
    """
    if dt.tzinfo is None:
        # Naive datetime -> UTC-aware (timezone bilgisi yok, UTC varsay)
        return dt.replace(tzinfo=timezone.utc)
    else:
        # Aware datetime -> UTC'ye çevir
        return dt.astimezone(timezone.utc)


async def check_double_booking(
    business_id: int,
    staff_id: int,
    appointment_date: datetime,
    service_ids: List[int],
    cursor: aiomysql.DictCursor,
    exclude_appointment_id: Optional[int] = None
) -> Tuple[bool, List[dict]]:
    """
    Double-booking kontrolü: Buffer time dahil çakışma var mı?
    
    Bu fonksiyon mevcut transaction içinde çalışmalıdır. SELECT FOR UPDATE ile
    ilgili appointment satırlarını kilitler, böylece race condition riski azalır.
    
    Args:
        business_id: Business ID (tenant-safe)
        staff_id: Staff ID
        appointment_date: Yeni randevunun başlangıç zamanı (aware veya naive, UTC'ye normalize edilir)
        service_ids: Yeni randevu için service ID listesi (duplicate'ler otomatik normalize edilir)
        cursor: Mevcut transaction içindeki database cursor (aynı connection)
        exclude_appointment_id: Opsiyonel appointment ID (update senaryosunda kendini hariç tutmak için)
    
    Returns:
        Tuple[bool, List[dict]]: (is_available, conflicting_appointments)
        - is_available: True ise çakışma yok, False ise çakışma var
        - conflicting_appointments: Çakışan randevuların listesi (boş liste ise is_available=True)
    
    Raises:
        ValueError: Geçersiz service_ids, service bulunamadı, veya toplam süre sıfır
    
    Note:
        Bu fonksiyon transaction içinde çalışmalıdır ve iki seviyeli locking yapar:
        1. staff_day_locks tablosunda deterministic lock (boş gün race condition önleme)
           - Effective window'un kapsadığı tüm günler için lock alınır (1, 2 veya 3 gün olabilir)
           - Lock alma sırası deterministik (day_date ascending) ki deadlock riski azalır
        2. appointments tablosunda SELECT ... FOR UPDATE (indeks-dostu range sorgusu, JOIN/GROUP BY olmadan)
           - Effective window aralığında çalışır (midnight/day-boundary edge-case'leri kapsar)
        
        DB seviyesindeki UNIQUE KEY (unique_business_staff_datetime) yalnızca "aynı start time"ı
        engeller; overlap (buffer time dahil) çakışmaları için tek başına yeterli değildir.
        Bu fonksiyon buffer time dahil overlap kontrolü sağlar ve midnight çakışmalarını yakalar.
    """
    # Business settings (buffer_time_minutes) - NULL güvenli
    await cursor.execute(
        "SELECT buffer_time_minutes FROM business_settings WHERE business_id = %s LIMIT 1",
        (business_id,)
    )
    settings = await cursor.fetchone()
    # NULL güvenliği: settings varsa ama buffer_time_minutes NULL ise default kullan
    # Tip güvenliği: Decimal/str gelebilir, int'e normalize et
    buffer_minutes_raw = (
        settings["buffer_time_minutes"] 
        if settings and settings.get("buffer_time_minutes") is not None 
        else 15
    )
    try:
        buffer_minutes = int(buffer_minutes_raw)
    except (TypeError, ValueError):
        buffer_minutes = 15  # Fallback
    
    # Service IDs doğrulaması (duplicate'leri normalize et)
    if not service_ids:
        raise ValueError("service_ids cannot be empty")
    
    # Duplicate'leri kaldır (DISTINCT mantığı)
    unique_service_ids = list(dict.fromkeys(service_ids))
    expected_distinct_count = len(unique_service_ids)
    
    # Tek sorguda doğrulama + toplam süre hesaplama (tenant-safe)
    placeholders = ','.join(['%s'] * len(unique_service_ids))
    await cursor.execute(
        f"""
        SELECT 
            COUNT(DISTINCT id) as found_count,
            COALESCE(SUM(duration_minutes), 0) as total_duration
        FROM services
        WHERE id IN ({placeholders}) AND business_id = %s AND is_active = TRUE
        """,
        (*unique_service_ids, business_id)
    )
    service_result = await cursor.fetchone()
    
    if not service_result:
        raise ValueError("Failed to query services")
    
    found_count = service_result["found_count"]
    new_duration_raw = service_result["total_duration"]
    
    # Tip güvenliği: Decimal/str gelebilir, int'e normalize et
    try:
        new_duration = int(new_duration_raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid service duration: {new_duration_raw}")
    
    # Validasyon: DISTINCT count kontrolü
    if found_count != expected_distinct_count:
        raise ValueError(
            f"One or more services not found or inactive. "
            f"Expected {expected_distinct_count} distinct service(s), found {found_count}"
        )
    
    if new_duration == 0:
        raise ValueError("Total service duration cannot be zero")
    
    # appointment_date'i UTC-aware'e normalize et
    new_start = _normalize_datetime_to_utc_aware(appointment_date)
    new_end = new_start + timedelta(minutes=new_duration)
    new_start_with_buffer = new_start - timedelta(minutes=buffer_minutes)
    new_end_with_buffer = new_end + timedelta(minutes=buffer_minutes)
    
    # Effective window hesapla (midnight/day-boundary edge-case için)
    # Buffer/duration yüzünden çakışma önceki/sonraki güne taşabilir
    # window_start: new_start_with_buffer'in gün başlangıcı (00:00:00, inclusive)
    # window_end: new_end_with_buffer'in gününden sonraki gün (00:00:00, exclusive)
    window_start = new_start_with_buffer.replace(hour=0, minute=0, second=0, microsecond=0)
    # new_end_with_buffer'in gününden sonraki gün (exclusive)
    window_end_date_start = new_end_with_buffer.replace(hour=0, minute=0, second=0, microsecond=0)
    window_end = window_end_date_start + timedelta(days=1)
    
    # Effective window'un kapsadığı tüm günleri hesapla (1, 2 veya 3 gün olabilir)
    day_dates = []
    current_date = window_start.date()
    window_end_date = window_end.date()
    while current_date < window_end_date:
        day_dates.append(current_date)
        current_date += timedelta(days=1)
    
    # A) Deterministic lock: Boş gün race condition önleme
    # Effective window'un kapsadığı her gün için staff_day_locks satırını "touch" et
    # Lock alma sırası deterministik olsun (day_date ascending) ki deadlock riski azalır
    for day_date in sorted(day_dates):  # Deterministic sıralama
        await cursor.execute(
            """
            INSERT INTO staff_day_locks (business_id, staff_id, day_date)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE id = id
            """,
            (business_id, staff_id, day_date)
        )
    
    # Her gün için SELECT ... FOR UPDATE ile lock al (deterministic sıralama)
    for day_date in sorted(day_dates):  # Deterministic sıralama (deadlock önleme)
        await cursor.execute(
            """
            SELECT id FROM staff_day_locks
            WHERE business_id = %s AND staff_id = %s AND day_date = %s
            FOR UPDATE
            """,
            (business_id, staff_id, day_date)
        )
        await cursor.fetchone()  # Lock'ı al, sonucu kullanmıyoruz
    
    # B) Base table appointments üzerinde indeks-dostu range sorgusu ile lock
    # Effective window aralığında çalış (midnight çakışmaları kaçmasın)
    # JOIN/GROUP BY olmadan, sadece appointments tablosunda lock al
    # Bu sorgu sadece appointment id + appointment_date döner
    lock_query_params = [business_id, staff_id, window_start, window_end]
    lock_query = """
        SELECT 
            id,
            appointment_date
        FROM appointments
        WHERE business_id = %s 
          AND staff_id = %s
          AND appointment_date >= %s
          AND appointment_date < %s
          AND status != 'cancelled'
    """
    
    if exclude_appointment_id is not None:
        lock_query += " AND id != %s"
        lock_query_params.append(exclude_appointment_id)
    
    lock_query += " ORDER BY appointment_date FOR UPDATE"
    
    await cursor.execute(lock_query, tuple(lock_query_params))
    locked_appointments = await cursor.fetchall()
    
    # C) Overlap hesaplaması için duration verisini lock aldıktan sonra çek
    # Lock'lanmış appointment_id listesi üzerinden duration hesapla
    if locked_appointments:
        appointment_ids = [apt['id'] for apt in locked_appointments]
        placeholders = ','.join(['%s'] * len(appointment_ids))
        
        await cursor.execute(
            f"""
            SELECT 
                a.id,
                COALESCE(SUM(s.duration_minutes), 0) as total_duration
            FROM appointments a
            INNER JOIN appointment_services aps ON aps.appointment_id = a.id
            INNER JOIN services s ON s.id = aps.service_id AND s.business_id = a.business_id
            WHERE a.business_id = %s AND a.id IN ({placeholders})
            GROUP BY a.id
            """,
            (business_id, *appointment_ids)
        )
        duration_results = await cursor.fetchall()
        
        # Duration map oluştur
        duration_map = {row['id']: row['total_duration'] for row in duration_results}
        
        # Lock'lanmış appointment'lara duration ekle
        existing_appointments = []
        for apt in locked_appointments:
            apt_id = apt['id']
            duration = duration_map.get(apt_id, 0)
            # Tip güvenliği: int'e normalize et
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                duration = 0
            existing_appointments.append({
                'id': apt_id,
                'appointment_date': apt['appointment_date'],
                'total_duration': duration
            })
    else:
        existing_appointments = []
    
    # Python'da overlap kontrolü (datetime normalizasyonu ile)
    conflicting = []
    for apt in existing_appointments:
        existing_start_raw = apt['appointment_date']
        
        # DB'den gelen datetime'ı UTC-aware'e normalize et
        if isinstance(existing_start_raw, str):
            # ISO string -> parse et
            existing_start = datetime.fromisoformat(existing_start_raw.replace('Z', '+00:00'))
        elif isinstance(existing_start_raw, datetime):
            existing_start = existing_start_raw
        else:
            # MySQL datetime objesi veya diğer tipler
            try:
                existing_start = datetime.combine(
                    existing_start_raw.date(), 
                    existing_start_raw.time()
                ) if hasattr(existing_start_raw, 'date') else datetime.fromisoformat(str(existing_start_raw))
            except (AttributeError, ValueError):
                raise ValueError(f"Invalid appointment_date format: {type(existing_start_raw)}")
        
        # UTC-aware'e normalize et
        existing_start = _normalize_datetime_to_utc_aware(existing_start)
        
        existing_duration = apt['total_duration']
        existing_end = existing_start + timedelta(minutes=existing_duration)
        existing_start_with_buffer = existing_start - timedelta(minutes=buffer_minutes)
        existing_end_with_buffer = existing_end + timedelta(minutes=buffer_minutes)
        
        # Overlap kontrolü: new_start_with_buffer < existing_end_with_buffer AND new_end_with_buffer > existing_start_with_buffer
        if new_start_with_buffer < existing_end_with_buffer and new_end_with_buffer > existing_start_with_buffer:
            conflicting.append(apt)
    
    is_available = len(conflicting) == 0
    return is_available, conflicting

