from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies import get_current_user
from app.db import get_db, get_connection
from app.models.schemas import TransactionCreate, TransactionUpdate, TransactionResponse
import aiomysql
import hashlib
from datetime import datetime

# Güvenli pymysql import - IntegrityError tuple pattern
try:
    import pymysql.err
    IntegrityErrors = (pymysql.err.IntegrityError,)
except Exception:
    IntegrityErrors = ()

router = APIRouter()

def _generate_idempotency_key(
    business_id: int,
    customer_id: int,
    appointment_id: int | None,
    amount: str,
    payment_method: str,
    status: str,
    timestamp_minute: str
) -> str:
    """Deterministic idempotency key generation"""
    # Format: business_id|customer_id|appointment_id(or 'null')|amount|payment_method|status|YYYY-MM-DD HH:MM
    appointment_str = str(appointment_id) if appointment_id is not None else 'null'
    key_string = f"{business_id}|{customer_id}|{appointment_str}|{amount}|{payment_method}|{status}|{timestamp_minute}"
    return hashlib.sha256(key_string.encode('utf-8')).hexdigest()

@router.post("/", response_model=TransactionResponse, summary="Create transaction", description="Create a new transaction with idempotency support")
async def create_transaction(
    transaction_data: TransactionCreate,
    current_user: dict = Depends(get_current_user)
):
    # business_id kontrolü
    business_id = current_user.get("business_id")
    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    
    # Idempotency key'i başta bir kere hesapla (hem INSERT hem duplicate SELECT'te aynı değeri kullan)
    if transaction_data.idempotency_key:
        idempotency_key = transaction_data.idempotency_key
    else:
        # Deterministic key üret: şu anki zamanı dakikaya yuvarla
        now = datetime.utcnow()
        timestamp_minute = now.strftime('%Y-%m-%d %H:%M')
        amount_str = str(transaction_data.amount)
        idempotency_key = _generate_idempotency_key(
            business_id=business_id,
            customer_id=transaction_data.customer_id,
            appointment_id=transaction_data.appointment_id,
            amount=amount_str,
            payment_method=transaction_data.payment_method,
            status=transaction_data.status,
            timestamp_minute=timestamp_minute
        )
    
    # Use get_connection() context manager for connection with ping check
    try:
        async with get_connection() as conn:
            transaction_id = None
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Customer'ın aynı business'a ait olduğunu kontrol et
                    await cursor.execute(
                        "SELECT id FROM customers WHERE id = %s AND business_id = %s LIMIT 1",
                        (transaction_data.customer_id, business_id)
                    )
                    if not await cursor.fetchone():
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Customer not found"
                        )
                    
                    # Appointment varsa aynı business'a ait olduğunu ve customer_id uyumunu kontrol et
                    if transaction_data.appointment_id is not None:
                        await cursor.execute(
                            "SELECT id, customer_id FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
                            (transaction_data.appointment_id, business_id)
                        )
                        appointment = await cursor.fetchone()
                        if not appointment:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail="Appointment not found"
                            )
                        
                        # Appointment'ın customer_id'si ile transaction'ın customer_id'si uyumlu olmalı
                        if appointment['customer_id'] != transaction_data.customer_id:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Invalid transaction data"
                            )
                    
                    # Transaction oluştur (idempotency_key başta hesaplanmış değeri kullan)
                    await cursor.execute(
                        "INSERT INTO transactions (business_id, appointment_id, customer_id, amount, payment_method, status, idempotency_key) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (business_id, transaction_data.appointment_id, transaction_data.customer_id, transaction_data.amount, transaction_data.payment_method, transaction_data.status, idempotency_key)
                    )
                    transaction_id = cursor.lastrowid
                
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
                    # Duplicate => 409 Conflict, idempotent davranış: mevcut transaction'ı döndür
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        # Idempotency key ile mevcut transaction'ı bul (başta hesaplanmış aynı key'i kullan)
                        await cursor.execute(
                            "SELECT id, business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date, created_at FROM transactions WHERE business_id = %s AND idempotency_key = %s LIMIT 1",
                            (business_id, idempotency_key)
                        )
                        existing_transaction = await cursor.fetchone()
                        
                        if existing_transaction:
                            # Mevcut transaction'ı döndür (idempotent)
                            return existing_transaction
                        else:
                            # Transaction bulunamadı, 409 dön
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail="Transaction already exists"
                            )
                else:
                    # Diğer IntegrityError'lar (FK vs) => 400 Bad Request
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid transaction data"
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
                        detail="Transaction already exists"
                    )
                
                # Diğer hatalar => 500 Internal Server Error
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create transaction"
                )
            
            # Commit başarılıysa buraya gelinir - Commit sonrası SELECT (tenant-safe, rollback yok)
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT id, business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date, created_at FROM transactions WHERE id = %s AND business_id = %s LIMIT 1",
                    (transaction_id, business_id)
                )
                transaction = await cursor.fetchone()
                
                if not transaction:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to retrieve created transaction"
                    )
                
                return transaction
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )

@router.put("/{transaction_id}", response_model=TransactionResponse, summary="Update transaction", description="Update an existing transaction")
async def update_transaction(
    transaction_id: int,
    transaction_data: TransactionUpdate,
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
            try:
                await conn.begin()
                
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Mevcut transaction'ı kontrol et (tenant-safe)
                    await cursor.execute(
                        "SELECT id, appointment_id, customer_id, amount, payment_method, status FROM transactions WHERE id = %s AND business_id = %s LIMIT 1",
                        (transaction_id, business_id)
                    )
                    existing_transaction = await cursor.fetchone()
                    
                    if not existing_transaction:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Transaction not found"
                        )
                    
                    # Güncellenecek değerleri belirle
                    update_fields = []
                    update_values = []
                    
                    if transaction_data.payment_method is not None:
                        update_fields.append("payment_method = %s")
                        update_values.append(transaction_data.payment_method)
                    
                    if transaction_data.status is not None:
                        update_fields.append("status = %s")
                        update_values.append(transaction_data.status)
                    
                    if not update_fields:
                        # Hiçbir alan güncellenmiyor, mevcut transaction'ı döndür
                        await conn.rollback()
                        await cursor.execute(
                            "SELECT id, business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date, created_at FROM transactions WHERE id = %s AND business_id = %s LIMIT 1",
                            (transaction_id, business_id)
                        )
                        return await cursor.fetchone()
                    
                    # Transaction'ı güncelle
                    update_values.append(transaction_id)
                    update_values.append(business_id)
                    
                    update_query = f"UPDATE transactions SET {', '.join(update_fields)} WHERE id = %s AND business_id = %s"
                    await cursor.execute(update_query, tuple(update_values))
                
                await conn.commit()
                
                # Commit sonrası SELECT (tenant-safe)
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT id, business_id, appointment_id, customer_id, amount, payment_method, status, transaction_date, created_at FROM transactions WHERE id = %s AND business_id = %s LIMIT 1",
                        (transaction_id, business_id)
                    )
                    transaction = await cursor.fetchone()
                    
                    if not transaction:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Failed to retrieve updated transaction"
                        )
                    
                    return transaction
            except HTTPException:
                await conn.rollback()
                raise
            except Exception as e:
                await conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update transaction: {str(e)}"
                )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database pool is not initialized"
        )
