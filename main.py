# ReplenMobile Backend
# FastAPI server for AI invoice parsing, barcode lookup, and multi-channel order sending

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Literal
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import services
from services.ai_service import parse_invoice
from services.product_service import lookup_barcode
from services.fax_service import generate_pdf, send_fax
from services.email_service import send_order_email, OrderItem as EmailOrderItem
from services.hanko_service import create_hanko_image
# LINE is handled by Flutter app via Deep Link - no backend needed

# Initialize FastAPI app
app = FastAPI(
    title="ReplenMobile API",
    description="AI-powered B2B ordering backend for Japanese businesses",
    version="2.0.0"
)

# Configure CORS for Flutter app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your app's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================
# Pydantic Models
# ===================

class OrderItem(BaseModel):
    """Individual item in an order"""
    name: str
    price: int
    quantity: int = 1
    barcode: Optional[str] = None

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
    price: Optional[int] = None
    image_url: Optional[str] = None
    category: Optional[str] = None

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
async def api_parse_invoice(request: InvoiceParseRequest):
    """
    Parse an invoice image using AI (GPT-4o Vision)
    
    Extracts product names, prices, and product codes from Japanese invoice images.
    """
    try:
        items = await parse_invoice(request.base64_image)
        return InvoiceParseResponse(items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse invoice: {str(e)}")


@app.get("/api/lookup/{barcode}", response_model=ProductLookupResponse)
async def api_lookup_barcode(barcode: str):
    """
    Lookup product information by barcode (JAN code)
    
    Uses Yahoo Japan Shopping API to find product details.
    """
    try:
        result = await lookup_barcode(barcode)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to lookup product: {str(e)}")


@app.post("/api/send-order", response_model=OrderSendResponse)
async def api_send_order(request: OrderRequest):
    """
    Send an order via fax (legacy endpoint - use /api/send-order-multi for new integrations)
    
    Generates a PDF invoice and sends it via ClickSend fax API.
    """
    try:
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
            fax_number=request.supplier_fax
        )
        
        # Clean up PDF file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        
        # send_fax returns OrderSendResponse directly
        result.method_used = "fax"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send order: {str(e)}")


@app.post("/api/send-order-multi", response_model=OrderSendResponse)
async def api_send_order_multi(request: MultiChannelOrderRequest):
    """
    Send an order via multiple channels (FAX, Email, or LINE)
    
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
                "barcode": item.barcode
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
