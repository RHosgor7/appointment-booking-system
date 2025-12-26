import aiomysql
from app.config import settings
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

pool = None

async def init_db():
    global pool
    # Idempotent: pool zaten varsa tekrar oluşturma
    if pool is not None:
        return
    pool = await aiomysql.create_pool(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        db=settings.DB_NAME,
        minsize=1,
        maxsize=10,
        autocommit=False,  # Transaction control manuel (begin/commit/rollback)
        charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
        # Isolation level: READ COMMITTED (default, transaction safety için yeterli)
        # Note: aiomysql pool'da isolation level parametresi yok, 
        # connection-level'da SET TRANSACTION ISOLATION LEVEL kullanılabilir
    )

async def close_db():
    global pool
    # Pool yoksa sessizce dön
    if pool is None:
        return
    pool.close()
    await pool.wait_closed()
    pool = None

async def get_db():
    if pool is None:
        raise RuntimeError("DB pool is not initialized")
    return pool

async def acquire_conn(pool):
    """
    Pool'dan connection alır ve ping kontrolü yapar.
    Bozuk connection varsa release edip yeni bir tane alır.
    
    Args:
        pool: aiomysql connection pool
        
    Returns:
        aiomysql.Connection: Valid, pinged connection
        
    Raises:
        RuntimeError: Pool boş veya 2. denemede de başarısız
    """
    conn = await pool.acquire()
    try:
        # Ping kontrolü (reconnect=True ile otomatik reconnect)
        await conn.ping(reconnect=True)
        return conn
    except Exception as e:
        # İlk connection bozuk, release et ve yeni bir tane al
        logger.warning(f"Connection ping failed, acquiring new connection: {str(e)}")
        try:
            # Bozuk connection'ı kapat ve release et
            conn.close()
        except Exception:
            pass  # Zaten kapalı olabilir
        
        try:
            pool.release(conn)
        except Exception:
            pass  # Release hatası olabilir, devam et
        
        # 1 kez daha acquire dene
        conn2 = await pool.acquire()
        try:
            await conn2.ping(reconnect=True)
            return conn2
        except Exception as e2:
            # 2. denemede de başarısız
            try:
                conn2.close()
            except Exception:
                pass
            try:
                pool.release(conn2)
            except Exception:
                pass
            logger.error(f"Failed to acquire valid connection after retry: {str(e2)}")
            raise RuntimeError(f"Failed to acquire valid database connection: {str(e2)}")

@asynccontextmanager
async def get_connection():
    """
    Context manager wrapper for database connection with ping check.
    Pool kontrolü yapar ve bozuk connection'ları otomatik olarak değiştirir.
    
    Usage:
        async with get_connection() as conn:
            # Use conn
            await conn.begin()
            # ... operations
            await conn.commit()
    """
    try:
        db_pool = await get_db()
    except RuntimeError:
        # HTTPException'a çevirmek için endpoint'lerde try/except kullanılabilir
        # veya burada HTTPException import edip fırlatılabilir
        # Şimdilik RuntimeError olarak bırakıyoruz, endpoint'lerde yakalanacak
        raise
    
    conn = await acquire_conn(db_pool)
    try:
        yield conn
    finally:
        # Connection'ı pool'a geri ver
        try:
            db_pool.release(conn)
        except Exception as e:
            logger.warning(f"Error releasing connection: {str(e)}")
            # Release başarısız olursa connection'ı kapat
            try:
                conn.close()
            except Exception:
                pass

def is_mysql_disconnect_error(error):
    """
    MySQL disconnect error kontrolü (2006, 2013).
    
    Args:
        error: Exception objesi
        
    Returns:
        bool: True ise MySQL disconnect error
    """
    error_code = None
    if hasattr(error, 'args') and error.args:
        try:
            error_code = int(error.args[0])
        except (TypeError, ValueError):
            pass
    
    # MySQL error codes: 2006 (server gone), 2013 (lost connection)
    if error_code in (2006, 2013):
        return True
    
    # String-based check (fallback)
    error_msg = str(error).lower()
    if any(phrase in error_msg for phrase in ['server has gone away', 'lost connection', 'connection lost']):
        return True
    
    return False

async def execute_with_retry(func, *args, max_retries=1, **kwargs):
    """
    MySQL disconnect error'ları için retry wrapper.
    Özellikle read işlemlerinde kullanılır.
    
    Args:
        func: Async function to execute
        *args: Function arguments
        max_retries: Maximum retry count (default: 1)
        **kwargs: Function keyword arguments
        
    Returns:
        Function return value
        
    Raises:
        Original exception if not a disconnect error or retries exhausted
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if is_mysql_disconnect_error(e) and attempt < max_retries:
                logger.warning(f"MySQL disconnect error (attempt {attempt + 1}/{max_retries + 1}): {str(e)}")
                # Retry için kısa bekleme (exponential backoff değil, basit)
                import asyncio
                await asyncio.sleep(0.1)
                continue
            # Disconnect error değil veya retry bitti, exception'ı fırlat
            raise
    
    # Buraya gelmemeli (yukarıda raise edilmeli)
    raise last_error
