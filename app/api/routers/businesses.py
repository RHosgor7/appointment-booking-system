from fastapi import APIRouter, Depends, HTTPException, status
from app.dependencies import get_current_user
from app.db import get_db
from app.models.schemas import BusinessResponse
import aiomysql

router = APIRouter()

@router.get("/me", response_model=BusinessResponse, summary="Get current business", description="Get the authenticated business's information")
async def get_my_business(current_user: dict = Depends(get_current_user)):
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
                "SELECT id, name, email, phone, address, created_at, updated_at FROM businesses WHERE id = %s LIMIT 1",
                (current_user["business_id"],)
            )
            business = await cursor.fetchone()
            
            if not business:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Business not found"
                )
            
            return business
