# Analytics Router for ReplenMobile
# Provides spending summaries and supplier analytics

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import os
import httpx

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# ===================
# Response Models
# ===================

class AnalyticsSummary(BaseModel):
    """Monthly analytics summary"""
    total_spend: int
    order_count: int
    supplier_count: int
    avg_order_value: int
    period: str  # "2025年12月" format

class TopSupplier(BaseModel):
    """Top supplier by spending"""
    supplier_id: str
    name: str
    total_spend: int
    order_count: int

class TopSuppliersResponse(BaseModel):
    """Response for top suppliers endpoint"""
    suppliers: List[TopSupplier]
    period: str

class FrequentProduct(BaseModel):
    """Frequently ordered product"""
    product_name: str
    total_quantity: int
    order_count: int

class MonthlySpending(BaseModel):
    """Spending data for a single month"""
    month: str  # "2025-12" format
    month_label: str  # "12月" format
    total_spend: int
    order_count: int

class MonthlyTrendResponse(BaseModel):
    """Response for monthly trend endpoint"""
    months: List[MonthlySpending]
    has_data: bool

# ===================
# Helper Functions
# ===================

def get_supabase_client():
    """Get Supabase URL and key from environment"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    
    if not supabase_url or not supabase_key:
        raise HTTPException(
            status_code=500,
            detail="Supabase credentials not configured"
        )
    
    return supabase_url, supabase_key

def get_month_start_end():
    """Get start and end of current month in ISO format"""
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Get next month start for end boundary
    if now.month == 12:
        month_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        month_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    
    return month_start.isoformat(), month_end.isoformat()

def format_period_japanese():
    """Format current month in Japanese"""
    now = datetime.now()
    return f"{now.year}年{now.month}月"

# ===================
# Endpoints
# ===================

@router.get("/summary", response_model=AnalyticsSummary)
async def get_monthly_summary(authorization: Optional[str] = Header(None)):
    """
    Get analytics summary for the current month.
    
    Returns:
    - total_spend: Sum of all order amounts this month
    - order_count: Number of orders sent this month
    - supplier_count: Number of unique suppliers ordered from
    - avg_order_value: Average order value
    - period: Current month in Japanese format
    """
    try:
        supabase_url, supabase_key = get_supabase_client()
        month_start, month_end = get_month_start_end()
        
        # Use service key for backend, or user's token if provided
        auth_key = supabase_key
        
        async with httpx.AsyncClient() as client:
            # Fetch orders for current month
            response = await client.get(
                f"{supabase_url}/rest/v1/orders",
                params={
                    "select": "id,total_amount,supplier_id,created_at",
                    "created_at": f"gte.{month_start}",
                    "created_at": f"lt.{month_end}",
                },
                headers={
                    "Authorization": f"Bearer {auth_key}",
                    "apikey": supabase_key,
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code != 200:
                # If filtering fails, try without date filter and filter in Python
                response = await client.get(
                    f"{supabase_url}/rest/v1/orders",
                    params={
                        "select": "id,total_amount,supplier_id,created_at",
                    },
                    headers={
                        "Authorization": f"Bearer {auth_key}",
                        "apikey": supabase_key,
                        "Content-Type": "application/json",
                    },
                )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch orders: {response.text}"
                )
            
            orders = response.json()
            
            # Filter by current month in Python (more reliable)
            month_start_dt = datetime.fromisoformat(month_start.replace('Z', '+00:00') if 'Z' in month_start else month_start)
            month_end_dt = datetime.fromisoformat(month_end.replace('Z', '+00:00') if 'Z' in month_end else month_end)
            
            filtered_orders = []
            for order in orders:
                if order.get('created_at'):
                    order_date_str = order['created_at']
                    # Handle various date formats
                    try:
                        if 'Z' in order_date_str:
                            order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                        elif '+' in order_date_str:
                            order_date = datetime.fromisoformat(order_date_str)
                        else:
                            order_date = datetime.fromisoformat(order_date_str)
                        
                        # Make comparison timezone-naive
                        order_date_naive = order_date.replace(tzinfo=None)
                        month_start_naive = month_start_dt.replace(tzinfo=None)
                        month_end_naive = month_end_dt.replace(tzinfo=None)
                        
                        if month_start_naive <= order_date_naive < month_end_naive:
                            filtered_orders.append(order)
                    except:
                        continue
            
            # Calculate metrics
            total_spend = sum(order.get('total_amount', 0) or 0 for order in filtered_orders)
            order_count = len(filtered_orders)
            unique_suppliers = set(order.get('supplier_id') for order in filtered_orders if order.get('supplier_id'))
            supplier_count = len(unique_suppliers)
            avg_order_value = total_spend // order_count if order_count > 0 else 0
            
            return AnalyticsSummary(
                total_spend=total_spend,
                order_count=order_count,
                supplier_count=supplier_count,
                avg_order_value=avg_order_value,
                period=format_period_japanese(),
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate analytics: {str(e)}"
        )

@router.get("/top-suppliers", response_model=TopSuppliersResponse)
async def get_top_suppliers(
    limit: int = 5,
    all_time: bool = False,
    authorization: Optional[str] = Header(None)
):
    """
    Get top suppliers ranked by total spending.
    
    Parameters:
    - limit: Number of suppliers to return (default 5)
    - all_time: If true, considers all orders; otherwise current month only
    
    Returns list of suppliers with their total spend and order count.
    """
    try:
        supabase_url, supabase_key = get_supabase_client()
        auth_key = supabase_key
        
        async with httpx.AsyncClient() as client:
            # Fetch all orders with supplier info
            response = await client.get(
                f"{supabase_url}/rest/v1/orders",
                params={
                    "select": "id,total_amount,supplier_id,supplier_name,created_at",
                },
                headers={
                    "Authorization": f"Bearer {auth_key}",
                    "apikey": supabase_key,
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch orders: {response.text}"
                )
            
            orders = response.json()
            
            # Filter by current month if not all_time
            if not all_time:
                month_start, month_end = get_month_start_end()
                month_start_dt = datetime.fromisoformat(month_start)
                month_end_dt = datetime.fromisoformat(month_end)
                
                filtered_orders = []
                for order in orders:
                    if order.get('created_at'):
                        try:
                            order_date_str = order['created_at']
                            if 'Z' in order_date_str:
                                order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                            elif '+' in order_date_str:
                                order_date = datetime.fromisoformat(order_date_str)
                            else:
                                order_date = datetime.fromisoformat(order_date_str)
                            
                            order_date_naive = order_date.replace(tzinfo=None)
                            month_start_naive = month_start_dt.replace(tzinfo=None)
                            month_end_naive = month_end_dt.replace(tzinfo=None)
                            
                            if month_start_naive <= order_date_naive < month_end_naive:
                                filtered_orders.append(order)
                        except:
                            continue
                orders = filtered_orders
            
            # Aggregate by supplier
            supplier_stats = {}
            for order in orders:
                supplier_id = order.get('supplier_id') or 'unknown'
                supplier_name = order.get('supplier_name') or '不明な仕入先'
                amount = order.get('total_amount', 0) or 0
                
                if supplier_id not in supplier_stats:
                    supplier_stats[supplier_id] = {
                        'supplier_id': supplier_id,
                        'name': supplier_name,
                        'total_spend': 0,
                        'order_count': 0,
                    }
                
                supplier_stats[supplier_id]['total_spend'] += amount
                supplier_stats[supplier_id]['order_count'] += 1
                # Keep the most recent name
                if supplier_name and supplier_name != '不明な仕入先':
                    supplier_stats[supplier_id]['name'] = supplier_name
            
            # Sort by total spend and take top N
            sorted_suppliers = sorted(
                supplier_stats.values(),
                key=lambda x: x['total_spend'],
                reverse=True
            )[:limit]
            
            top_suppliers = [
                TopSupplier(
                    supplier_id=s['supplier_id'],
                    name=s['name'],
                    total_spend=s['total_spend'],
                    order_count=s['order_count'],
                )
                for s in sorted_suppliers
            ]
            
            return TopSuppliersResponse(
                suppliers=top_suppliers,
                period=format_period_japanese() if not all_time else "全期間",
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get top suppliers: {str(e)}"
        )

@router.get("/frequent-products")
async def get_frequent_products(
    limit: int = 10,
    authorization: Optional[str] = Header(None)
):
    """
    Get most frequently ordered products.
    
    Returns list of products ranked by total quantity ordered.
    """
    try:
        supabase_url, supabase_key = get_supabase_client()
        auth_key = supabase_key
        
        async with httpx.AsyncClient() as client:
            # Fetch all order items
            response = await client.get(
                f"{supabase_url}/rest/v1/order_items",
                params={
                    "select": "product_name,quantity",
                },
                headers={
                    "Authorization": f"Bearer {auth_key}",
                    "apikey": supabase_key,
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch order items: {response.text}"
                )
            
            items = response.json()
            
            # Aggregate by product name
            product_stats = {}
            for item in items:
                name = item.get('product_name', '不明')
                quantity = item.get('quantity', 1) or 1
                
                if name not in product_stats:
                    product_stats[name] = {
                        'product_name': name,
                        'total_quantity': 0,
                        'order_count': 0,
                    }
                
                product_stats[name]['total_quantity'] += quantity
                product_stats[name]['order_count'] += 1
            
            # Sort by quantity and take top N
            sorted_products = sorted(
                product_stats.values(),
                key=lambda x: x['total_quantity'],
                reverse=True
            )[:limit]
            
            return {
                "products": sorted_products,
                "period": "全期間",
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get frequent products: {str(e)}"
        )

@router.get("/monthly-trend", response_model=MonthlyTrendResponse)
async def get_monthly_trend(
    months: int = 6,
    authorization: Optional[str] = Header(None)
):
    """
    Get monthly spending trend for the past N months.
    Only returns months that have actual data.
    
    Parameters:
    - months: Maximum number of months to look back (default 6)
    
    Returns list of monthly spending data (only months with orders).
    """
    try:
        supabase_url, supabase_key = get_supabase_client()
        auth_key = supabase_key
        
        async with httpx.AsyncClient() as client:
            # Fetch all orders
            response = await client.get(
                f"{supabase_url}/rest/v1/orders",
                params={
                    "select": "id,total_amount,created_at",
                    "order": "created_at.asc",
                },
                headers={
                    "Authorization": f"Bearer {auth_key}",
                    "apikey": supabase_key,
                    "Content-Type": "application/json",
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to fetch orders: {response.text}"
                )
            
            orders = response.json()
            
            if not orders:
                return MonthlyTrendResponse(months=[], has_data=False)
            
            # Aggregate by month
            monthly_stats = {}
            for order in orders:
                if not order.get('created_at'):
                    continue
                    
                try:
                    order_date_str = order['created_at']
                    if 'Z' in order_date_str:
                        order_date = datetime.fromisoformat(order_date_str.replace('Z', '+00:00'))
                    elif '+' in order_date_str:
                        order_date = datetime.fromisoformat(order_date_str)
                    else:
                        order_date = datetime.fromisoformat(order_date_str)
                    
                    # Create month key
                    month_key = order_date.strftime("%Y-%m")
                    month_label = f"{order_date.month}月"
                    
                    if month_key not in monthly_stats:
                        monthly_stats[month_key] = {
                            'month': month_key,
                            'month_label': month_label,
                            'total_spend': 0,
                            'order_count': 0,
                        }
                    
                    monthly_stats[month_key]['total_spend'] += order.get('total_amount', 0) or 0
                    monthly_stats[month_key]['order_count'] += 1
                except:
                    continue
            
            # Sort by month and take the last N months with data
            sorted_months = sorted(monthly_stats.values(), key=lambda x: x['month'])
            
            # Only keep the last N months
            if len(sorted_months) > months:
                sorted_months = sorted_months[-months:]
            
            monthly_spending = [
                MonthlySpending(
                    month=m['month'],
                    month_label=m['month_label'],
                    total_spend=m['total_spend'],
                    order_count=m['order_count'],
                )
                for m in sorted_months
            ]
            
            return MonthlyTrendResponse(
                months=monthly_spending,
                has_data=len(monthly_spending) > 0,
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get monthly trend: {str(e)}"
        )
