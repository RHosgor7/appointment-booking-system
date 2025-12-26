from datetime import datetime, timedelta, time
from typing import Optional
from decimal import Decimal
import aiomysql
from zoneinfo import ZoneInfo


async def get_available_slots(
    business_id: int,
    staff_id: int,
    date: str,
    db_pool,
    service_ids: Optional[list[int]] = None
) -> dict:
    """
    Belirli bir tarihte staff için uygun slot'ları döndürür.
    Business settings'ten slot_length ve buffer_time alır.
    Mevcut randevuları ve buffer time'ı dikkate alarak gerçek uygunluk hesabı yapar.
    
    Args:
        business_id: Business ID
        staff_id: Staff ID
        date: Tarih (YYYY-MM-DD formatında)
        db_pool: Database connection pool
        service_ids: Opsiyonel service ID listesi (verilirse slot süresi bu service'lerin toplam süresine göre hesaplanır)
    
    Returns:
        dict: {"available_slots": [...], "timezone": "<tz>", "slot_duration_minutes": X}
    
    Raises:
        ValueError: Geçersiz tarih formatı, staff bulunamadı, geçersiz service_ids
    """
    # Tarih formatı kontrolü
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Expected YYYY-MM-DD")
    
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Staff doğrulaması (tenant-safe)
            await cursor.execute(
                "SELECT id FROM staff WHERE id = %s AND business_id = %s AND is_active = TRUE LIMIT 1",
                (staff_id, business_id)
            )
            if not await cursor.fetchone():
                raise ValueError(f"Staff not found or inactive for business_id={business_id}")
            
            # Business settings'i al
            await cursor.execute(
                "SELECT slot_length_minutes, buffer_time_minutes, working_hours_start, working_hours_end, timezone FROM business_settings WHERE business_id = %s LIMIT 1",
                (business_id,)
            )
            settings = await cursor.fetchone()
            
            # Default değerler
            slot_length = 30
            buffer_time = 15
            start_time = time(9, 0)  # 09:00
            end_time = time(18, 0)   # 18:00
            timezone_str = "Europe/Istanbul"
            
            if settings:
                # Convert to int in case MySQL returns Decimal
                slot_length_raw = settings.get("slot_length_minutes") or 30
                buffer_time_raw = settings.get("buffer_time_minutes") or 15
                slot_length = int(slot_length_raw) if slot_length_raw else 30
                buffer_time = int(buffer_time_raw) if buffer_time_raw else 15
                timezone_str = settings.get("timezone") or "Europe/Istanbul"
                
                # working_hours_start/end parse et (MySQL'den TIME tipi farklı formatlarda gelebilir)
                from datetime import timedelta
                
                start_time_raw = settings.get("working_hours_start")
                end_time_raw = settings.get("working_hours_end")
                
                # Parse working_hours_start
                if start_time_raw is not None and start_time_raw != '':
                    if isinstance(start_time_raw, str):
                        # String format: "HH:MM:SS" veya "HH:MM"
                        try:
                            if len(start_time_raw.split(':')) == 2:
                                start_time = datetime.strptime(start_time_raw, "%H:%M").time()
                            else:
                                start_time = datetime.strptime(start_time_raw, "%H:%M:%S").time()
                        except ValueError:
                            # Fallback: try to parse manually
                            parts = start_time_raw.split(':')
                            h, m = int(parts[0]), int(parts[1])
                            s = int(parts[2]) if len(parts) > 2 else 0
                            start_time = time(h, m, s)
                    elif isinstance(start_time_raw, time):
                        start_time = start_time_raw
                    elif isinstance(start_time_raw, timedelta):
                        # timedelta'dan time'a çevir
                        total_seconds = int(start_time_raw.total_seconds())
                        h = total_seconds // 3600
                        m = (total_seconds % 3600) // 60
                        s = total_seconds % 60
                        start_time = time(h, m, s)
                    # else: default değer zaten set edilmiş (09:00)
                
                # Parse working_hours_end
                if end_time_raw is not None and end_time_raw != '':
                    if isinstance(end_time_raw, str):
                        # String format: "HH:MM:SS" veya "HH:MM"
                        try:
                            if len(end_time_raw.split(':')) == 2:
                                end_time = datetime.strptime(end_time_raw, "%H:%M").time()
                            else:
                                end_time = datetime.strptime(end_time_raw, "%H:%M:%S").time()
                        except ValueError:
                            # Fallback: try to parse manually
                            parts = end_time_raw.split(':')
                            h, m = int(parts[0]), int(parts[1])
                            s = int(parts[2]) if len(parts) > 2 else 0
                            end_time = time(h, m, s)
                    elif isinstance(end_time_raw, time):
                        end_time = end_time_raw
                    elif isinstance(end_time_raw, timedelta):
                        # timedelta'dan time'a çevir
                        total_seconds = int(end_time_raw.total_seconds())
                        h = total_seconds // 3600
                        m = (total_seconds % 3600) // 60
                        s = total_seconds % 60
                        end_time = time(h, m, s)
                    # else: default değer zaten set edilmiş (18:00)
                
                # Debug: Log the parsed values
                print(f"DEBUG availability_service: working_hours_end raw: {end_time_raw}, type: {type(end_time_raw)}, parsed: {end_time}")
            
            # Working hours validation
            if end_time <= start_time:
                raise ValueError("Invalid working hours: end_time must be after start_time")
            
            # Service süresi hesaplama
            slot_duration = slot_length  # Default: slot_length
            
            if service_ids is not None:
                if len(service_ids) == 0:
                    raise ValueError("service_ids is required (cannot be empty list)")
                
                # Service'lerin aynı business'a ait olduğunu ve aktif olduğunu kontrol et
                placeholders = ','.join(['%s'] * len(service_ids))
                await cursor.execute(
                    f"SELECT id, duration_minutes FROM services WHERE id IN ({placeholders}) AND business_id = %s AND is_active = TRUE",
                    (*service_ids, business_id)
                )
                services = await cursor.fetchall()
                
                if len(services) != len(service_ids):
                    raise ValueError("One or more services not found or inactive")
                
                # Toplam duration hesapla (convert Decimal to int for timedelta compatibility)
                slot_duration = sum(int(s['duration_minutes']) for s in services)
            
            # Mevcut randevuları çek (tenant-safe)
            await cursor.execute(
                """
                SELECT 
                    a.id, 
                    a.appointment_date AS start_dt, 
                    SUM(s.duration_minutes) AS dur
                FROM appointments a
                INNER JOIN appointment_services aps ON aps.appointment_id = a.id
                INNER JOIN services s ON s.id = aps.service_id AND s.business_id = %s
                WHERE a.business_id = %s 
                  AND a.staff_id = %s
                  AND DATE(a.appointment_date) = %s
                  AND a.status != 'cancelled'
                GROUP BY a.id, a.appointment_date
                ORDER BY a.appointment_date
                """,
                (business_id, business_id, staff_id, date)
            )
            appointments = await cursor.fetchall()
            
            # Blocked intervals hesapla (buffer time ile)
            blocked_intervals = []
            for apt in appointments:
                start_dt = apt['start_dt']
                
                # Parse start_dt to datetime
                if isinstance(start_dt, str):
                    try:
                        start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
                    except ValueError:
                        # Try other formats
                        try:
                            start_dt = datetime.strptime(start_dt, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            start_dt = datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S")
                elif not isinstance(start_dt, datetime):
                    # MySQL datetime objesi veya date objesi
                    if hasattr(start_dt, 'time'):
                        start_dt = datetime.combine(date_obj, start_dt.time())
                    elif hasattr(start_dt, 'date'):
                        # It's a date object, combine with time(0,0)
                        start_dt = datetime.combine(start_dt, time(0, 0))
                    else:
                        # Fallback
                        start_dt = datetime.combine(date_obj, time(0, 0))
                
                # Ensure start_dt is timezone-naive (local time)
                if start_dt.tzinfo is not None:
                    start_dt = start_dt.replace(tzinfo=None)
                
                duration_minutes = apt.get('dur') or 0
                if duration_minutes is None:
                    duration_minutes = 0
                # Convert Decimal to int for timedelta
                if isinstance(duration_minutes, Decimal):
                    duration_minutes = int(duration_minutes)
                else:
                    duration_minutes = int(duration_minutes)
                end_dt = start_dt + timedelta(minutes=duration_minutes)
                
                # Buffer uygula
                blocked_start = start_dt - timedelta(minutes=buffer_time)
                blocked_end = end_dt + timedelta(minutes=buffer_time)
                
                blocked_intervals.append((blocked_start, blocked_end))
            
            # Blocked intervals'ı merge et (overlap edenleri birleştir)
            if blocked_intervals:
                blocked_intervals.sort(key=lambda x: x[0])
                merged = [blocked_intervals[0]]
                for current in blocked_intervals[1:]:
                    last = merged[-1]
                    if current[0] <= last[1]:
                        # Overlap var, merge et
                        merged[-1] = (last[0], max(last[1], current[1]))
                    else:
                        merged.append(current)
                blocked_intervals = merged
            
            # Working window oluştur (naive local time)
            working_start = datetime.combine(date_obj, start_time)
            working_end = datetime.combine(date_obj, end_time)
            
            # Bugün ise geçmiş slot'ları filtrele
            # Use business timezone to get "now" in the business's local time,
            # then convert to naive local time to match working_start/working_end.
            # This ensures all datetime comparisons are naive-to-naive and avoids
            # "can't compare offset-naive and offset-aware datetimes" errors.
            try:
                tz = ZoneInfo(timezone_str)
                now_aware = datetime.now(tz)
                # Convert to naive local time by removing timezone info
                now = now_aware.replace(tzinfo=None)
            except Exception:
                # Fallback to system local time if timezone parsing fails
                now = datetime.now()
            
            if date_obj == now.date():
                min_slot_start = max(working_start, now.replace(second=0, microsecond=0))
            else:
                min_slot_start = working_start
            
            # Slot'ları üret ve çakışma kontrolü yap
            available_slots = []
            current_slot_start = working_start
            
            # Slot adımı: slot_length_minutes (settings'teki slot_length ile adımla)
            while current_slot_start < working_end:
                # Slot süresi service_ids'e göre belirlenir
                current_slot_end = current_slot_start + timedelta(minutes=slot_duration)
                
                # Slot working hours içinde mi?
                if current_slot_end > working_end:
                    break
                
                # Geçmişte kalan slot'ları atla (bugün ise)
                if current_slot_start < min_slot_start:
                    current_slot_start += timedelta(minutes=slot_length)
                    continue
                
                # Çakışma kontrolü: slot interval hiçbir blocked interval ile overlap etmemeli
                overlaps = False
                for blocked_start, blocked_end in blocked_intervals:
                    # Overlap koşulu: not (slot_end <= blocked_start or slot_start >= blocked_end)
                    if not (current_slot_end <= blocked_start or current_slot_start >= blocked_end):
                        overlaps = True
                        break
                
                if not overlaps:
                    # ISO format string üret
                    available_slots.append(current_slot_start.isoformat())
                
                # Sonraki slot'a geç
                current_slot_start += timedelta(minutes=slot_length)
            
            return {
                "available_slots": available_slots,
                "timezone": timezone_str,
                "slot_duration_minutes": slot_duration
            }
