# ReplenMobile Backend
# FastAPI server for AI invoice parsing, barcode lookup, and multi-channel order sending

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Literal
import os
import logging
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import services
from services.ai_service import parse_invoice
from services.product_service import lookup_barcode
from services.fax_service import generate_pdf, send_fax
from services.email_service import send_order_email, OrderItem as EmailOrderItem
from services.hanko_service import create_hanko_image
# LINE is handled by Flutter app via Deep Link - no backend needed

# Import routers
from routers.analytics import router as analytics_router

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize FastAPI app
app = FastAPI(
    title="ReplenMobile API",
    description="AI-powered B2B ordering backend for Japanese businesses",
    version="2.0.0"
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS for Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://replen-backend-production.up.railway.app",  # Production backend
        "http://localhost:*",  # Local development
        "https://xvmfekxkxforianncgob.supabase.co",  # Supabase
    ] if os.getenv("ENVIRONMENT") == "production" else ["*"],  # Allow all in dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analytics_router)

# ===================
# Startup Validation
# ===================

@app.on_event("startup")
async def validate_environment():
    """Validate required environment variables on startup"""
    required_vars = {
        "OPENAI_API_KEY": "AI invoice parsing will not work",
        "SUPABASE_URL": "Analytics endpoints will not work",
    }
    
    recommended_vars = {
        "YAHOO_API_KEY": "Barcode lookup will return mock data",
        "CLICKSEND_USERNAME": "FAX sending will not work",
        "CLICKSEND_API_KEY": "FAX sending will not work",
    }
    
    missing_required = []
    missing_recommended = []
    
    # Check required variables
    for var, description in required_vars.items():
        if not os.getenv(var):
            missing_required.append(f"  - {var}: {description}")
            logger.error(f"REQUIRED: Missing environment variable {var}")
    
    # Check recommended variables
    for var, description in recommended_vars.items():
        if not os.getenv(var):
            missing_recommended.append(f"  - {var}: {description}")
            logger.warning(f"OPTIONAL: Missing environment variable {var}")
    
    # Fail if required variables are missing
    if missing_required:
        error_msg = "Missing required environment variables:\n" + "\n".join(missing_required)
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Warn about recommended variables
    if missing_recommended:
        warning_msg = "Missing recommended environment variables:\n" + "\n".join(missing_recommended)
        logger.warning(warning_msg)
    
    logger.info("✅ Environment validation passed")

# ===================
# Pydantic Models
# ===================

class OrderItem(BaseModel):
    """Individual item in an order"""
    name: str
    price: int
    quantity: int = 1
    barcode: Optional[str] = None
    unit: Optional[str] = "個"  # 箱, 本, 個, パック, kg, 袋

class OrderRequest(BaseModel):
    """Request to send an order via fax (legacy endpoint)"""
    items: List[OrderItem]
    supplier_fax: str
    supplier_name: Optional[str] = None
    hanko_url: Optional[str] = None
    note: Optional[str] = None  # User memo (備考)
    sender_name: Optional[str] = None  # Ordering company/store name
    sender_phone: Optional[str] = None  # Callback phone number

class MultiChannelOrderRequest(BaseModel):
    """Request to send an order via any channel (FAX, Email, LINE)"""
    items: List[OrderItem]
    supplier_name: str
    contact_method: Literal["fax", "email", "line"]
    # FAX fields
    fax_number: Optional[str] = None
    # Email fields
    email: Optional[str] = None
    # LINE fields
    line_id: Optional[str] = None
    # Optional
    hanko_url: Optional[str] = None
    order_id: Optional[str] = None  # For reference tracking
    note: Optional[str] = None  # User memo (備考)
    sender_name: Optional[str] = None  # Ordering company/store name
    sender_phone: Optional[str] = None  # Callback phone number

class InvoiceParseRequest(BaseModel):
    """Request to parse an invoice image"""
    base64_image: str

class ParsedItem(BaseModel):
    """Parsed item from invoice"""
    name: str
    price: int
    product_code: Optional[str] = None

class InvoiceParseResponse(BaseModel):
    """Response from invoice parsing"""
    items: List[ParsedItem]
    raw_text: Optional[str] = None

class ProductLookupResponse(BaseModel):
    """Response from barcode lookup"""
    found: bool
    barcode: str
    name: Optional[str] = None
    price: Optional[int] = None  # Pack/case price from Yahoo
    image_url: Optional[str] = None
    category: Optional[str] = None
    suggested_unit: Optional[str] = None  # 箱, 本, 個, パック, kg, 袋
    pack_quantity: Optional[int] = None  # Number of items in pack (e.g., 48)
    unit_price: Optional[int] = None  # Calculated: price / pack_quantity

class OrderSendResponse(BaseModel):
    """Response from sending an order"""
    success: bool
    message: str
    confirmation_id: Optional[str] = None
    method_used: Optional[str] = None

class HankoRequest(BaseModel):
    """Request to generate a company seal (hanko)"""
    text: str  # 1-4 Japanese characters
    user_id: str  # Supabase user ID

class HankoResponse(BaseModel):
    """Response from hanko generation"""
    success: bool
    hanko_url: Optional[str] = None
    message: str

# ===================
# Health Check
# ===================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": "ReplenMobile API",
        "version": "2.0.0"
    }

@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "services": {
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "yahoo": bool(os.getenv("YAHOO_API_KEY")),
            "clicksend": bool(os.getenv("CLICKSEND_USERNAME")),
            "email_smtp": bool(os.getenv("SMTP_HOST")),
            "email_resend": bool(os.getenv("RESEND_API_KEY")),
        },
        "note": "LINE sending is handled by Flutter app via Deep Link"
    }

# ===================
# API Endpoints
# ===================

@app.post("/api/parse-invoice", response_model=InvoiceParseResponse)
@limiter.limit("10/minute")  # Limit to 10 invoice parses per minute
async def api_parse_invoice(request: Request, parse_request: InvoiceParseRequest):
    """
    Parse an invoice image using AI (GPT-4o Vision)
    
    Rate limit: 10 requests per minute per IP
    
    Extracts product names, prices, and product codes from Japanese invoice images.
    """
    try:
        logger.info(f"Parsing invoice from {get_remote_address(request)}")
        items = await parse_invoice(parse_request.base64_image)
        logger.info(f"Successfully parsed {len(items)} items")
        return InvoiceParseResponse(items=items)
    except Exception as e:
        logger.error(f"Failed to parse invoice: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to parse invoice: {str(e)}")


@app.get("/api/lookup/{barcode}", response_model=ProductLookupResponse)
@limiter.limit("30/minute")  # Limit to 30 barcode lookups per minute
async def api_lookup_barcode(request: Request, barcode: str):
    """
    Lookup product information by barcode (JAN code)
    
    Rate limit: 30 requests per minute per IP
    
    Uses Yahoo Japan Shopping API to find product details.
    """
    try:
        logger.info(f"Looking up barcode {barcode} from {get_remote_address(request)}")
        result = await lookup_barcode(barcode)
        logger.info(f"Barcode lookup {'found' if result.found else 'not found'}: {barcode}")
        return result
    except Exception as e:
        logger.error(f"Failed to lookup product {barcode}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to lookup product: {str(e)}")


@app.post("/api/send-order", response_model=OrderSendResponse)
@limiter.limit("20/hour")  # Limit to 20 orders per hour
async def api_send_order(request: Request, order_request: OrderRequest):
    """
    Send an order via fax (legacy endpoint - use /api/send-order-multi for new integrations)
    
    Rate limit: 20 requests per hour per IP
    
    Generates a PDF invoice and sends it via ClickSend fax API.
    """
    try:
        logger.info(f"Sending order via FAX from {get_remote_address(request)}")
        # Generate PDF
        pdf_path = generate_pdf(
            items=order_request.items,
            supplier_name=order_request.supplier_name,
            hanko_url=order_request.hanko_url,
            note=order_request.note,
            sender_name=order_request.sender_name,
            sender_phone=order_request.sender_phone,
        )
        
        # Send fax
        result = send_fax(
            pdf_path=pdf_path,
            fax_number=order_request.supplier_fax
        )
        
        # Clean up PDF file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        
        logger.info(f"Order sent via FAX: {result.success}")
        
        # Return response with method_used
        return OrderSendResponse(
            success=result.success,
            message=result.message,
            confirmation_id=result.confirmation_id,
            method_used="fax"
        )
    except Exception as e:
        logger.error(f"Failed to send order via FAX: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send order: {str(e)}")


class PreviewPdfRequest(BaseModel):
    """Request to generate PDF preview (without sending)"""
    items: List[OrderItem]
    supplier_name: Optional[str] = None
    hanko_url: Optional[str] = None
    note: Optional[str] = None
    sender_name: Optional[str] = None
    sender_phone: Optional[str] = None


@app.post("/api/preview-pdf")
async def api_preview_pdf(request: PreviewPdfRequest):
    """
    Generate a PDF preview of the order (with hanko) without sending.
    
    Returns the PDF file directly for download.
    Use this for email sharing via native share sheet.
    """
    try:
        # Generate PDF with hanko
        pdf_path = generate_pdf(
            items=request.items,
            supplier_name=request.supplier_name,
            hanko_url=request.hanko_url,
            note=request.note,
            sender_name=request.sender_name,
            sender_phone=request.sender_phone,
        )
        
        # Return PDF file
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=f"order_{request.supplier_name or 'preview'}.pdf",
            background=None  # Don't delete file in background
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


@app.post("/api/send-order-multi", response_model=OrderSendResponse)
@limiter.limit("20/hour")  # Limit to 20 orders per hour
async def api_send_order_multi(request: Request, order_request: MultiChannelOrderRequest):
    """
    Send an order via multiple channels (FAX, Email, or LINE)
    
    Rate limit: 20 requests per hour per IP
    
    Routes the order to the appropriate service based on contact_method.
    - FAX: Generates PDF and sends via ClickSend
    - Email: Sends formatted HTML email with order details
    - LINE: Sends rich Flex Message via LINE Messaging API
    """
    try:
        # Convert items to the format expected by each service
        items_dict = [
            {
                "name": item.name,
                "price": item.price,
                "quantity": item.quantity,
                "barcode": item.barcode,
                "unit": item.unit
            }
            for item in request.items
        ]
        
        # Route to appropriate service based on contact method
        if request.contact_method == "fax":
            # Validate FAX number
            if not request.fax_number:
                raise HTTPException(status_code=400, detail="FAX番号が必要です")
            
            # Generate PDF
            pdf_path = generate_pdf(
                items=request.items,
                supplier_name=request.supplier_name,
                hanko_url=request.hanko_url,
                note=request.note,
                sender_name=request.sender_name,
                sender_phone=request.sender_phone,
            )
            
            # Send fax
            result = send_fax(
                pdf_path=pdf_path,
                fax_number=request.fax_number
            )
            
            # Clean up PDF file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            
            return OrderSendResponse(
                success=result.get("success", False),
                message=result.get("message", "FAXで注文を送信しました"),
                confirmation_id=result.get("confirmation_id"),
                method_used="fax"
            )
            
        elif request.contact_method == "email":
            # Validate email
            if not request.email:
                raise HTTPException(status_code=400, detail="メールアドレスが必要です")
            
            # Convert items for email service
            email_items = [
                EmailOrderItem(
                    name=item.name,
                    price=item.price,
                    quantity=item.quantity,
                    barcode=item.barcode
                )
                for item in request.items
            ]
            
            # Generate PDF for attachment (optional)
            pdf_path = None
            try:
                pdf_path = generate_pdf(
                    items=request.items,
                    supplier_name=request.supplier_name,
                    hanko_url=request.hanko_url,
                    note=request.note,
                    sender_name=request.sender_name,
                    sender_phone=request.sender_phone,
                )
            except Exception:
                pass  # PDF is optional for email
            
            # Send email
            result = await send_order_email(
                items=email_items,
                supplier_name=request.supplier_name,
                to_email=request.email,
                pdf_path=pdf_path,
                note=request.note
            )
            
            # Clean up PDF file
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
            
            return OrderSendResponse(
                success=result.get("success", False),
                message=result.get("message", "メールで注文を送信しました"),
                confirmation_id=result.get("confirmation_id"),
                method_used="email"
            )
            
        elif request.contact_method == "line":
            # LINE is handled by Flutter app via Deep Link
            # This endpoint should NOT be called for LINE
            # Return informative message in case it's called by mistake
            return OrderSendResponse(
                success=False,
                message="LINE送信はアプリから直接行われます。このAPIは使用されません。",
                confirmation_id=None,
                method_used="line"
            )
            
        else:
            raise HTTPException(status_code=400, detail=f"未対応の送信方法: {request.contact_method}")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注文送信に失敗しました: {str(e)}")


# ===================
# Hanko (Company Seal) Endpoint
# ===================

@app.post("/api/generate-hanko", response_model=HankoResponse)
async def api_generate_hanko(request: HankoRequest):
    """
    Generate a digital company seal (電子印鑑/hanko).
    
    Creates a traditional Japanese seal image with the provided text (1-4 characters),
    uploads it to Supabase Storage, and updates the user's profile with the URL.
    """
    import base64
    import httpx
    import uuid
    
    # Validate text
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="印鑑のテキストが必要です")
    if len(text) > 4:
        raise HTTPException(status_code=400, detail="テキストは4文字以内にしてください")
    
    try:
        # Generate hanko image
        image_bytes = create_hanko_image(text)
        image_data = image_bytes.getvalue()
        
        # Get Supabase credentials
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        if not supabase_url or not supabase_key:
            # Dev mode - return base64 image URL
            b64_image = base64.b64encode(image_data).decode('utf-8')
            data_url = f"data:image/png;base64,{b64_image}"
            return HankoResponse(
                success=True,
                hanko_url=data_url,
                message="[DEV MODE] 印鑑を生成しました（Supabase未設定）"
            )
        
        # Upload to Supabase Storage
        bucket_name = "company-assets"
        file_name = f"hanko/{request.user_id}/{uuid.uuid4().hex}.png"
        
        async with httpx.AsyncClient() as client:
            # Upload file
            upload_response = await client.post(
                f"{supabase_url}/storage/v1/object/{bucket_name}/{file_name}",
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "image/png",
                    "x-upsert": "true",  # Overwrite if exists
                },
                content=image_data
            )
            
            if upload_response.status_code not in [200, 201]:
                # Try creating bucket if it doesn't exist
                await client.post(
                    f"{supabase_url}/storage/v1/bucket",
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                    },
                    json={"id": bucket_name, "name": bucket_name, "public": True}
                )
                # Retry upload
                upload_response = await client.post(
                    f"{supabase_url}/storage/v1/object/{bucket_name}/{file_name}",
                    headers={
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "image/png",
                        "x-upsert": "true",
                    },
                    content=image_data
                )
            
            if upload_response.status_code not in [200, 201]:
                raise Exception(f"Storage upload failed: {upload_response.text}")
            
            # Get public URL
            hanko_url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{file_name}"
            
            # Update user profile with hanko_url
            update_response = await client.patch(
                f"{supabase_url}/rest/v1/profiles?id=eq.{request.user_id}",
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "apikey": supabase_key,
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={"hanko_url": hanko_url}
            )
            
            if update_response.status_code not in [200, 204]:
                print(f"Warning: Could not update profile: {update_response.text}")
        
        return HankoResponse(
            success=True,
            hanko_url=hanko_url,
            message="印鑑を保存しました"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"印鑑の生成に失敗しました: {str(e)}")


# ===================
# Run Server
# ===================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )
