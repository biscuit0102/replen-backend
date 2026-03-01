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
from reportlab.lib.utils import simpleSplit
from pydantic import BaseModel
import httpx

# Try to register Japanese font
# Use absolute path to ensure font is found regardless of working directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Goes up to /backend
FONT_PATH = os.path.join(BASE_DIR, "fonts", "ipaexg.ttf")

if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont('JPN', FONT_PATH))
        JAPANESE_FONT = 'JPN'
        print(f"SUCCESS: Japanese font loaded from {FONT_PATH}")
    except Exception as e:
        print(f"ERROR: Failed to register font: {e}")
        JAPANESE_FONT = 'Helvetica'
else:
    print(f"WARNING: Font not found at {FONT_PATH}, falling back to Helvetica")
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
    unit: Optional[str] = "個"  # 箱, 本, 個, パック, kg, 袋


class OrderSendResponse(BaseModel):
    """Response from sending order"""
    success: bool
    message: str
    confirmation_id: Optional[str] = None


def generate_pdf(
    items: List[OrderItem],
    supplier_name: Optional[str] = None,
    hanko_url: Optional[str] = None,
    note: Optional[str] = None,
    sender_name: Optional[str] = None,
    sender_phone: Optional[str] = None,
) -> str:
    """
    Generate a PDF invoice for faxing.
    
    Args:
        items: List of order items
        supplier_name: Name of the supplier (displayed on invoice)
        hanko_url: URL to hanko image for stamping
        note: Optional user memo (備考)
        sender_name: Name of the ordering company/store
        sender_phone: Phone number for callbacks
        
    Returns:
        Path to generated PDF file
    """
    # Create temporary file for PDF
    pdf_filename = f"order_{uuid.uuid4().hex[:8]}.pdf"
    pdf_path = os.path.join(tempfile.gettempdir(), pdf_filename)

    # SECURITY: Escape all user-supplied strings before they enter ReportLab
    # Paragraph() parses its content as XML — unescaped '<', '>', '&' cause XMLSyntaxError
    # and could be used to inject ReportLab markup tags.
    import html as _html
    safe_supplier_name = _html.escape(supplier_name) if supplier_name else None
    safe_sender_name   = _html.escape(sender_name)   if sender_name   else None
    safe_sender_phone  = _html.escape(sender_phone)  if sender_phone  else None
    raw_note           = note.strip() if note and note.strip() else "特になし"
    safe_note          = _html.escape(raw_note)

    # Create PDF document
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )
    
    # Build content
    elements = []
    styles = getSampleStyleSheet()
    
    # ===================
    # FAX-SAFE STYLES (Black text on white background - no colors!)
    # ===================
    
    title_style = ParagraphStyle(
        'JapaneseTitle',
        parent=styles['Heading1'],
        fontName=JAPANESE_FONT,
        fontSize=28,
        alignment=1,  # Center
        spaceAfter=5*mm,
        textColor=colors.black,
    )
    
    # Large bold style for sender info (CRITICAL for fax identification)
    sender_style = ParagraphStyle(
        'SenderInfo',
        parent=styles['Normal'],
        fontName=JAPANESE_FONT,
        fontSize=14,
        leading=20,
        textColor=colors.black,
        alignment=2,  # Right align
    )
    
    normal_style = ParagraphStyle(
        'JapaneseNormal',
        parent=styles['Normal'],
        fontName=JAPANESE_FONT,
        fontSize=10,
        textColor=colors.black,
    )
    
    recipient_style = ParagraphStyle(
        'Recipient',
        parent=styles['Normal'],
        fontName=JAPANESE_FONT,
        fontSize=12,
        textColor=colors.black,
    )
    
    # ===================
    # HEADER: Title
    # ===================
    elements.append(Paragraph("注 文 書", title_style))
    elements.append(Spacer(1, 3*mm))
    
    # ===================
    # SENDER INFO (Top Right - LARGE and BOLD for easy identification)
    # ===================
    today = datetime.now().strftime("%Y年%m月%d日")
    
    # Build sender block (right-aligned)
    sender_block = f"<b>発注元:</b><br/>"
    if safe_sender_name:
        sender_block += f"<b>{safe_sender_name}</b><br/>"
    else:
        sender_block += "<b>ReplenMobile ユーザー</b><br/>"
    if safe_sender_phone:
        sender_block += f"TEL: {safe_sender_phone}<br/>"
    sender_block += f"日付: {today}"
    
    # Create a 2-column layout: Recipient (left) | Sender (right)
    # This ensures both are visible at a glance
    recipient_text = ""
    if safe_supplier_name:
        recipient_text = f"<b>{safe_supplier_name} 御中</b>"
    
    header_table = Table(
        [[Paragraph(recipient_text, recipient_style), Paragraph(sender_block, sender_style)]],
        colWidths=[90*mm, 80*mm]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8*mm))
    
    # ===================
    # GREETING
    # ===================
    elements.append(Paragraph("いつもお世話になっております。下記の通りご注文申し上げます。", normal_style))
    elements.append(Spacer(1, 6*mm))
    
    # ===================
    # ORDER ITEMS TABLE (FAX-SAFE: Black text, white background, black borders)
    # ===================
    total_amount = sum(item.price * item.quantity for item in items)
    
    table_data = [
        ["No.", "商品名", "単価", "数量", "金額"]
    ]
    
    for i, item in enumerate(items, 1):
        subtotal = item.price * item.quantity
        # Display quantity with unit (e.g., "3 箱", "5 本")
        unit = item.unit or "個"
        quantity_display = f"{item.quantity} {unit}"
        table_data.append([
            str(i),
            item.name,
            f"¥{item.price:,}",
            quantity_display,
            f"¥{subtotal:,}"
        ])
    
    # Add total row
    table_data.append(["", "", "", "合計", f"¥{total_amount:,}"])
    
    # Create table with FAX-SAFE styling (no colored backgrounds!)
    table = Table(table_data, colWidths=[12*mm, 85*mm, 25*mm, 18*mm, 30*mm])
    table.setStyle(TableStyle([
        # Header row - WHITE background, BLACK text, BLACK border
        ('BACKGROUND', (0, 0), (-1, 0), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('FONTNAME', (0, 0), (-1, 0), JAPANESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black),  # Thick line under header
        ('LINEABOVE', (0, 0), (-1, 0), 1.5, colors.black),  # Thick line above header
        
        # Data rows
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), JAPANESE_FONT),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # No. column centered
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),  # Price columns right-aligned
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        
        # Total row - slightly bold
        ('FONTNAME', (0, -1), (-1, -1), JAPANESE_FONT),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), 1.5, colors.black),  # Thick bottom line
        
        # Vertical grid lines
        ('LINEBEFORE', (0, 0), (0, -1), 1, colors.black),  # Left edge
        ('LINEAFTER', (-1, 0), (-1, -1), 1, colors.black),  # Right edge
        ('LINEBEFORE', (1, 0), (1, -1), 0.5, colors.black),
        ('LINEBEFORE', (2, 0), (2, -1), 0.5, colors.black),
        ('LINEBEFORE', (3, 0), (3, -1), 0.5, colors.black),
        ('LINEBEFORE', (4, 0), (4, -1), 0.5, colors.black),
        
        # Horizontal lines for data rows
        ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.grey),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 8*mm))
    
    # ===================
    # NOTES BOX (備考欄)
    # ===================
    # safe_note was already computed and escaped above
    note_content = safe_note
    
    note_content_style = ParagraphStyle(
        'NoteContent',
        parent=styles['Normal'],
        fontName=JAPANESE_FONT,
        fontSize=9,
        leading=14,
        textColor=colors.black,
    )
    
    note_paragraph = Paragraph(f"<b>■ 備考:</b><br/>{note_content}", note_content_style)
    
    notes_table = Table([[note_paragraph]], colWidths=[170*mm])
    notes_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    elements.append(notes_table)
    elements.append(Spacer(1, 10*mm))
    
    # ===================
    # CLOSING
    # ===================
    elements.append(Paragraph("以上、よろしくお願い申し上げます。", normal_style))
    
    # Build PDF
    doc.build(elements)
    
    # Add hanko stamp if provided
    if hanko_url:
        _add_hanko_stamp(pdf_path, hanko_url)
    
    return pdf_path


def _is_allowed_hanko_url(url: str) -> bool:
    """
    Validate that a hanko URL points to the expected Supabase Storage bucket.
    This prevents SSRF attacks where an attacker could supply an internal
    network address or AWS metadata endpoint as the hanko_url.
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        # Must be HTTPS
        if parsed.scheme != "https":
            return False
        # Must be the configured Supabase project domain
        supabase_url = os.getenv("SUPABASE_URL", "")
        if supabase_url:
            from urllib.parse import urlparse as _up
            allowed_host = _up(supabase_url).hostname or ""
        else:
            # Fallback: accept any *.supabase.co storage URL
            allowed_host = ""
        host = parsed.hostname or ""
        if allowed_host:
            if host != allowed_host:
                return False
        else:
            # Fallback check: must end with .supabase.co
            if not host.endswith(".supabase.co"):
                return False
        # Must be under the public storage path
        if not parsed.path.startswith("/storage/v1/object/public/"):
            return False
        return True
    except Exception:
        return False


def _add_hanko_stamp(pdf_path: str, hanko_url: str):
    """
    Add hanko stamp to PDF (overlay on right side of sender name).
    Uses PyPDF2 to merge a hanko overlay PDF.
    """
    import requests
    from PyPDF2 import PdfReader, PdfWriter
    from PIL import Image
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    import io

    # SECURITY: Validate URL before fetching to prevent SSRF
    if not _is_allowed_hanko_url(hanko_url):
        print(f"SECURITY: Rejected hanko_url with disallowed host/scheme: {hanko_url}")
        return

    # Download hanko image
    response = requests.get(hanko_url, timeout=10)
    if response.status_code != 200:
        print(f"Failed to download hanko image: {hanko_url}")
        return
    hanko_img = Image.open(io.BytesIO(response.content)).convert("RGBA")

    # Scale to 1.5cm x 1.5cm (about 43 points in PDF)
    stamp_size = 43  # points (1.5cm)
    
    # Position: right side of sender info area
    # A4: 595x842 points. Place stamp near sender name
    x = 480  # points from left
    y = 735  # points from bottom

    # Create overlay PDF with just the hanko
    overlay_buffer = io.BytesIO()
    c = canvas.Canvas(overlay_buffer, pagesize=A4)
    
    # Save hanko image to temp buffer
    img_buffer = io.BytesIO()
    hanko_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    
    # Draw hanko on overlay
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(img_buffer), x, y, width=stamp_size, height=stamp_size, mask='auto')
    c.save()
    overlay_buffer.seek(0)

    # Merge overlay onto original PDF
    original = PdfReader(pdf_path)
    overlay = PdfReader(overlay_buffer)
    
    writer = PdfWriter()
    page = original.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)
    
    # Add remaining pages if any
    for i in range(1, len(original.pages)):
        writer.add_page(original.pages[i])
    
    with open(pdf_path, 'wb') as f:
        writer.write(f)
    
    print(f"Hanko stamp added to PDF at position ({x}, {y})")


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
