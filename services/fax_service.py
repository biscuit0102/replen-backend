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
    if sender_name:
        sender_block += f"<b>{sender_name}</b><br/>"
    else:
        sender_block += "<b>ReplenMobile ユーザー</b><br/>"
    if sender_phone:
        sender_block += f"TEL: {sender_phone}<br/>"
    sender_block += f"日付: {today}"
    
    # Create a 2-column layout: Recipient (left) | Sender (right)
    # This ensures both are visible at a glance
    recipient_text = ""
    if supplier_name:
        recipient_text = f"<b>{supplier_name} 御中</b>"
    
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
        table_data.append([
            str(i),
            item.name,
            f"¥{item.price:,}",
            str(item.quantity),
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
    note_content = note.strip() if note and note.strip() else "特になし"
    
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


def _add_hanko_stamp(pdf_path: str, hanko_url: str):
    """
    Add hanko stamp to PDF (overlay on right side of sender name).
    Uses PyPDF2 and Pillow to overlay PNG with transparency.
    """
    import requests
    from PyPDF2 import PdfReader, PdfWriter
    from PIL import Image
    import io

    # Download hanko image
    response = requests.get(hanko_url)
    if response.status_code != 200:
        print(f"Failed to download hanko image: {hanko_url}")
        return
    hanko_img = Image.open(io.BytesIO(response.content)).convert("RGBA")

    # Scale to 1.5cm x 1.5cm (about 43x43 pixels at 300dpi)
    target_size_px = int(1.5 / 2.54 * 300)  # 1.5cm in pixels at 300dpi
    hanko_img = hanko_img.resize((target_size_px, target_size_px), Image.LANCZOS)

    # Read PDF
    reader = PdfReader(pdf_path)
    page = reader.pages[0]

    # Calculate position: right side of sender name (approximate)
    # A4: 595x842 points. Place stamp at (x, y) near top right, below title and date
    x = 420  # points from left
    y = 730  # points from bottom

    # Convert hanko image to bytes
    img_byte_arr = io.BytesIO()
    hanko_img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    # Overlay image using PyPDF2 (add as XObject)
    from PyPDF2.generic import NameObject, DictionaryObject, StreamObject
    from PyPDF2.pdf import PageObject
    from PyPDF2.utils import b_ as py_b_

    # Create XObject for image
    img_data = img_byte_arr.read()
    img_stream = StreamObject()
    img_stream._data = py_b_(img_data)
    img_stream.update({
        NameObject('/Type'): NameObject('/XObject'),
        NameObject('/Subtype'): NameObject('/Image'),
        NameObject('/Width'): target_size_px,
        NameObject('/Height'): target_size_px,
        NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
        NameObject('/BitsPerComponent'): 8,
        NameObject('/Filter'): NameObject('/FlateDecode'),
    })

    # Add image to page resources
    xobj_name = NameObject('/HankoStamp')
    if '/XObject' not in page['/Resources']:
        page['/Resources'][NameObject('/XObject')] = DictionaryObject()
    page['/Resources']['/XObject'][xobj_name] = img_stream

    # Add stamp to content stream
    stamp_cmd = f"q\n{target_size_px} 0 0 {target_size_px} {x} {y} cm\n/HankoStamp Do\nQ\n"
    if '/Contents' in page:
        orig_content = page['/Contents'].get_data().decode('latin1')
        new_content = orig_content + stamp_cmd
        page['/Contents']._data = py_b_(new_content)

    # Write new PDF
    writer = PdfWriter()
    writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


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
