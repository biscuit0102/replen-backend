# ReplenMobile Fax Service
# Generates PDF invoices and sends them via ClickSend API

import os
import uuid
import tempfile
from datetime import datetime
from typing import List, Optional
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pydantic import BaseModel
import httpx

# Try to register Japanese font
try:
    FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "fonts", "ipaexg.ttf")
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont('JPN', FONT_PATH))
        JAPANESE_FONT = 'JPN'
    else:
        JAPANESE_FONT = 'Helvetica'  # Fallback
except Exception:
    JAPANESE_FONT = 'Helvetica'

# ClickSend API configuration
CLICKSEND_USERNAME = os.getenv("CLICKSEND_USERNAME", "")
CLICKSEND_API_KEY = os.getenv("CLICKSEND_API_KEY", "")
CLICKSEND_API_URL = "https://rest.clicksend.com/v3"


class OrderItem(BaseModel):
    """Order item for PDF generation"""
    name: str
    price: int
    quantity: int = 1
    barcode: Optional[str] = None


class OrderSendResponse(BaseModel):
    """Response from sending order"""
    success: bool
    message: str
    confirmation_id: Optional[str] = None


def generate_pdf(
    items: List[OrderItem],
    supplier_name: Optional[str] = None,
    hanko_url: Optional[str] = None
) -> str:
    """
    Generate a PDF invoice for faxing.
    
    Args:
        items: List of order items
        supplier_name: Name of the supplier (displayed on invoice)
        hanko_url: URL to hanko image for stamping
        
    Returns:
        Path to generated PDF file
    """
    # Create temporary file for PDF
    pdf_filename = f"order_{uuid.uuid4().hex[:8]}.pdf"
    pdf_path = os.path.join(tempfile.gettempdir(), pdf_filename)
    
    # Create PDF document
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # Build content
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles for Japanese text
    title_style = ParagraphStyle(
        'JapaneseTitle',
        parent=styles['Heading1'],
        fontName=JAPANESE_FONT,
        fontSize=24,
        alignment=1,  # Center
        spaceAfter=10*mm
    )
    
    normal_style = ParagraphStyle(
        'JapaneseNormal',
        parent=styles['Normal'],
        fontName=JAPANESE_FONT,
        fontSize=10
    )
    
    # Header
    elements.append(Paragraph("注文書", title_style))
    elements.append(Spacer(1, 5*mm))
    
    # Date and order info
    today = datetime.now().strftime("%Y年%m月%d日")
    elements.append(Paragraph(f"日付: {today}", normal_style))
    
    if supplier_name:
        elements.append(Paragraph(f"宛先: {supplier_name} 御中", normal_style))
    
    elements.append(Spacer(1, 10*mm))
    
    # Calculate totals
    total_amount = sum(item.price * item.quantity for item in items)
    
    # Order items table
    table_data = [
        ["No.", "商品名", "単価", "数量", "金額"]
    ]
    
    for i, item in enumerate(items, 1):
        subtotal = item.price * item.quantity
        table_data.append([
            str(i),
            item.name,
            f"¥{item.price:,}",
            str(item.quantity),
            f"¥{subtotal:,}"
        ])
    
    # Add total row
    table_data.append(["", "", "", "合計", f"¥{total_amount:,}"])
    
    # Create and style table
    table = Table(table_data, colWidths=[15*mm, 80*mm, 25*mm, 20*mm, 30*mm])
    table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.1, 0.14, 0.49)),  # Navy blue
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), JAPANESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), JAPANESE_FONT),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # No. column
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),  # Price columns
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        
        # Total row
        ('FONTNAME', (0, -1), (-1, -1), JAPANESE_FONT),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('BACKGROUND', (3, -1), (-1, -1), colors.Color(0.95, 0.95, 0.95)),
        
        # Grid
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.black),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 15*mm))
    
    # Footer note
    elements.append(Paragraph("よろしくお願いいたします。", normal_style))
    
    # Build PDF
    doc.build(elements)
    
    # Add hanko stamp if provided
    if hanko_url:
        _add_hanko_stamp(pdf_path, hanko_url)
    
    return pdf_path


def _add_hanko_stamp(pdf_path: str, hanko_url: str):
    """
    Add hanko stamp to PDF (overlay on bottom right).
    
    Note: This is a simplified version. Full implementation would use
    PyPDF2 or pikepdf to overlay the image.
    """
    # For now, just log that we would add the stamp
    print(f"Would add hanko from: {hanko_url}")
    # TODO: Implement actual hanko overlay using PyPDF2


def send_fax(pdf_path: str, fax_number: str) -> OrderSendResponse:
    """
    Send PDF via fax using ClickSend API.
    
    Args:
        pdf_path: Path to PDF file
        fax_number: Recipient fax number (international format)
        
    Returns:
        OrderSendResponse with success status and confirmation ID
    """
    if not CLICKSEND_USERNAME or not CLICKSEND_API_KEY:
        # Development mode - simulate success
        return OrderSendResponse(
            success=True,
            message="[DEV MODE] FAX送信をシミュレートしました",
            confirmation_id=f"DEV-{uuid.uuid4().hex[:8].upper()}"
        )
    
    try:
        import base64
        
        # Read PDF file
        with open(pdf_path, "rb") as f:
            pdf_content = base64.b64encode(f.read()).decode()
        
        # Upload file to ClickSend
        with httpx.Client() as client:
            # Upload
            upload_response = client.post(
                f"{CLICKSEND_API_URL}/uploads",
                auth=(CLICKSEND_USERNAME, CLICKSEND_API_KEY),
                json={
                    "content": pdf_content,
                    "convert": "fax"  # Convert to fax format
                }
            )
            
            if upload_response.status_code != 200:
                return OrderSendResponse(
                    success=False,
                    message=f"Failed to upload PDF: {upload_response.text}"
                )
            
            upload_data = upload_response.json()
            file_url = upload_data.get("data", {}).get("_url")
            
            if not file_url:
                return OrderSendResponse(
                    success=False,
                    message="Failed to get uploaded file URL"
                )
            
            # Send fax
            fax_response = client.post(
                f"{CLICKSEND_API_URL}/fax/send",
                auth=(CLICKSEND_USERNAME, CLICKSEND_API_KEY),
                json={
                    "file_url": file_url,
                    "messages": [
                        {
                            "to": fax_number,
                            "source": "ReplenMobile",
                            "schedule": 0,  # Send immediately
                            "custom_string": f"Order-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        }
                    ]
                }
            )
            
            if fax_response.status_code == 200:
                fax_data = fax_response.json()
                message_id = fax_data.get("data", {}).get("messages", [{}])[0].get("message_id")
                
                return OrderSendResponse(
                    success=True,
                    message="FAXを送信しました",
                    confirmation_id=message_id
                )
            else:
                return OrderSendResponse(
                    success=False,
                    message=f"Failed to send fax: {fax_response.text}"
                )
                
    except Exception as e:
        return OrderSendResponse(
            success=False,
            message=f"Fax service error: {str(e)}"
        )
