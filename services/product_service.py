# ReplenMobile Product Service
# Uses Yahoo Japan Shopping API to lookup product information by barcode

import os
import httpx
from typing import Optional
from pydantic import BaseModel


class ProductLookupResponse(BaseModel):
    """Product lookup result"""
    found: bool
    barcode: str
    name: Optional[str] = None
    price: Optional[int] = None
    image_url: Optional[str] = None
    category: Optional[str] = None


# Yahoo Japan Shopping API configuration
YAHOO_API_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
YAHOO_APP_ID = os.getenv("YAHOO_API_KEY", "")


async def lookup_barcode(jan_code: str) -> ProductLookupResponse:
    """
    Lookup product information by JAN barcode using Yahoo Japan Shopping API.
    
    Args:
        jan_code: JAN barcode (Japanese Article Number, same as EAN/UPC)
        
    Returns:
        ProductLookupResponse with product details or found=False
    """
    # Validate barcode format
    if not jan_code or not jan_code.isdigit():
        return ProductLookupResponse(found=False, barcode=jan_code)
    
    if not YAHOO_APP_ID:
        # Fallback: Return mock data for development
        return _get_mock_product(jan_code)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                YAHOO_API_URL,
                params={
                    "appid": YAHOO_APP_ID,
                    "jan_code": jan_code,
                    "results": 1,
                    "sort": "-score",  # Best match first
                },
                timeout=10.0
            )
            
            if response.status_code != 200:
                return ProductLookupResponse(found=False, barcode=jan_code)
            
            data = response.json()
            
            # Check if any hits found
            total_results = data.get("totalResultsAvailable", 0)
            if total_results == 0:
                return ProductLookupResponse(found=False, barcode=jan_code)
            
            # Extract first result
            hits = data.get("hits", [])
            if not hits:
                return ProductLookupResponse(found=False, barcode=jan_code)
            
            item = hits[0]
            
            return ProductLookupResponse(
                found=True,
                barcode=jan_code,
                name=item.get("name", ""),
                price=int(item.get("price", 0)),
                image_url=_get_image_url(item),
                category=_get_category(item)
            )
            
    except Exception as e:
        print(f"Yahoo API error: {e}")
        return ProductLookupResponse(found=False, barcode=jan_code)


def _get_image_url(item: dict) -> Optional[str]:
    """Extract image URL from Yahoo API response"""
    image = item.get("image", {})
    
    # Try different image sizes
    for size in ["medium", "small"]:
        url = image.get(size)
        if url:
            return url
    
    return None


def _get_category(item: dict) -> Optional[str]:
    """Extract category from Yahoo API response"""
    genre_category = item.get("genreCategory", {})
    
    # Get the most specific category
    depth = genre_category.get("depth", 0)
    if depth > 0:
        return genre_category.get("name")
    
    return None


def _get_mock_product(jan_code: str) -> ProductLookupResponse:
    """
    Return mock product data for development/testing.
    In production, this would not be called if YAHOO_API_KEY is set.
    """
    # Common Japanese products for testing
    mock_products = {
        "4901201103742": ProductLookupResponse(
            found=True,
            barcode="4901201103742",
            name="アサヒ スーパードライ 350ml",
            price=220,
            image_url="https://via.placeholder.com/150?text=Asahi",
            category="ビール・発泡酒"
        ),
        "4901777254923": ProductLookupResponse(
            found=True,
            barcode="4901777254923",
            name="サントリー 烏龍茶 500ml",
            price=130,
            image_url="https://via.placeholder.com/150?text=Oolong",
            category="お茶飲料"
        ),
        "4902102112154": ProductLookupResponse(
            found=True,
            barcode="4902102112154",
            name="コカ・コーラ 500ml",
            price=150,
            image_url="https://via.placeholder.com/150?text=Coke",
            category="炭酸飲料"
        ),
        "4901681740413": ProductLookupResponse(
            found=True,
            barcode="4901681740413",
            name="サントリー角瓶 700ml",
            price=1200,
            image_url="https://via.placeholder.com/150?text=Kakubin",
            category="ウイスキー"
        ),
    }
    
    # Return mock if available, otherwise not found
    if jan_code in mock_products:
        return mock_products[jan_code]
    
    # For any unknown barcode in development, return a generic product
    return ProductLookupResponse(
        found=True,
        barcode=jan_code,
        name=f"テスト商品 ({jan_code[-4:]})",
        price=500,
        image_url="https://via.placeholder.com/150?text=Product",
        category="その他"
    )
