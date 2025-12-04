# ReplenMobile Product Service
# Uses Yahoo Japan Shopping API to lookup product information by barcode
# Uses GPT-4o-mini to clean SEO-stuffed product names

import os
import httpx
from typing import Optional
from pydantic import BaseModel
from openai import OpenAI

# Initialize OpenAI client
openai_client = OpenAI() if os.getenv("OPENAI_API_KEY") else None


class ProductLookupResponse(BaseModel):
    """Product lookup result"""
    found: bool
    barcode: str
    name: Optional[str] = None
    price: Optional[int] = None  # Pack price from Yahoo
    image_url: Optional[str] = None
    category: Optional[str] = None
    suggested_unit: Optional[str] = None  # 箱, 本, 個, etc.
    pack_quantity: Optional[int] = None  # Number of items in pack (e.g., 48)
    unit_price: Optional[int] = None  # Calculated: price / pack_quantity


# Yahoo Japan Shopping API configuration
YAHOO_API_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
YAHOO_APP_ID = os.getenv("YAHOO_API_KEY", "")


def clean_product_name(messy_title: str) -> dict:
    """
    Uses GPT-4o-mini to clean SEO-stuffed product names and extract quantity.
    
    Returns a dict with:
    - clean_name: The concise product name
    - quantity: Total number of items in the package (e.g., 48 for "24本×2ケース")
    - suggested_unit: '箱' if bulk/case, '本' for bottles, '個' otherwise
    
    Cost: ~$0.0001 per scan (basically free)
    Speed: ~0.5 seconds
    """
    if not openai_client:
        # Fallback if OpenAI not configured
        return {"clean_name": messy_title, "quantity": 1, "suggested_unit": "個"}
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Use MINI for speed/cost
            messages=[
                {
                    "role": "system",
                    "content": """You are a product parser for a Japanese inventory app.
Your job is to analyze e-commerce titles and extract THREE things:

1. **clean_name**: Remove SEO garbage like:
   - 送料無料, Free Shipping, 即納, 業務用
   - Sale, セール, 特価, お買い得
   - Store names, emojis, 【】「」
   KEEP: Brand name, product variant, size (500ml, 2L, 350ml)

2. **quantity**: The TOTAL number of items in the package.
   - Look for patterns like "24本", "48本", "x12", "6缶", "ケース"
   - If it says "2ケース x 24本" → calculate 48
   - If it says "6本パック" → return 6
   - If it's a single item or quantity not mentioned → return 1
   - For weight items like "5kg" → return 1 (it's 1 bag)

3. **suggested_unit**: The default ordering unit
   - If title contains ケース, case, 本入 → "箱" (case)
   - If it's bottles/cans → "本"
   - If it's food/general items → "個"
   - If it's by weight → "kg"

Respond in this exact JSON format only:
{"clean_name": "ブランド名 商品名 容量", "quantity": 48, "suggested_unit": "箱"}"""
                },
                {
                    "role": "user",
                    "content": messy_title
                }
            ],
            max_tokens=150,
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        import json
        result = json.loads(response.choices[0].message.content.strip())
        return {
            "clean_name": result.get("clean_name", messy_title),
            "quantity": result.get("quantity", 1),
            "suggested_unit": result.get("suggested_unit", "個")
        }
        
    except Exception as e:
        print(f"AI Cleaning failed: {e}")
        # Fallback to original if AI fails
        return {"clean_name": messy_title, "quantity": 1, "suggested_unit": "個"}


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
            
            # Get raw name from Yahoo
            raw_name = item.get("name", "")
            
            # Clean the name using AI (removes SEO garbage, extracts quantity)
            cleaned = clean_product_name(raw_name)
            
            # Get pack price from Yahoo
            pack_price = int(item.get("price", 0))
            pack_quantity = cleaned.get("quantity", 1)
            
            # Calculate unit price (with safety check for division by zero)
            unit_price = pack_price // pack_quantity if pack_quantity > 0 else pack_price
            
            return ProductLookupResponse(
                found=True,
                barcode=jan_code,
                name=cleaned["clean_name"],
                price=pack_price,  # This is the pack/case price
                image_url=_get_image_url(item),
                category=_get_category(item),
                suggested_unit=cleaned["suggested_unit"],
                pack_quantity=pack_quantity,
                unit_price=unit_price
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
