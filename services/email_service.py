# ReplenMobile Email Service
# Sends order PDFs via email using SMTP or Resend API

import os
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import List, Optional
from pydantic import BaseModel
import httpx

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ReplenMobile")

# Resend API (alternative to SMTP)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "orders@yourdomain.com")


class OrderItem(BaseModel):
    """Order item for email"""
    name: str
    price: int
    quantity: int = 1


class EmailSendResult(BaseModel):
    """Result from sending email"""
    success: bool
    message: str
    confirmation_id: Optional[str] = None


def generate_order_html(
    items: List[OrderItem],
    supplier_name: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """
    Generate HTML email body for the order.
    """
    import html as _html
    from datetime import datetime
    
    today = datetime.now().strftime("%Y年%m月%d日")
    total = sum(item.price * item.quantity for item in items)

    # SECURITY: Escape all user-controlled strings before HTML interpolation.
    # Without this, a malicious item name / supplier name / note could inject
    # arbitrary HTML tags that break the email layout or reputation-flag it.
    safe_supplier = _html.escape(supplier_name) if supplier_name else None
    raw_note = note.strip() if note and note.strip() else "特になし"
    note_content = _html.escape(raw_note)
    
    # Build items table rows
    items_html = ""
    for i, item in enumerate(items, 1):
        subtotal = item.price * item.quantity
        safe_name = _html.escape(item.name)
        items_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: center;">{i}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">{safe_name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">¥{item.price:,}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: center;">{item.quantity}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">¥{subtotal:,}</td>
        </tr>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>注文書</title>
    </head>
    <body style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #1A237E, #3949AB); color: white; padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="margin: 0; font-size: 28px;">📦 注文書</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">ReplenMobile からの発注</p>
        </div>
        
        <div style="background: #f8f9fa; padding: 20px; border: 1px solid #eee;">
            <table style="width: 100%;">
                <tr>
                    <td><strong>日付:</strong> {today}</td>
                </tr>
                {"<tr><td><strong>宛先:</strong> " + safe_supplier + " 御中</td></tr>" if safe_supplier else ""}
            </table>
        </div>
        
        <div style="padding: 20px; border: 1px solid #eee; border-top: none;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background: #1A237E; color: white;">
                        <th style="padding: 12px; text-align: center; width: 50px;">No.</th>
                        <th style="padding: 12px; text-align: left;">商品名</th>
                        <th style="padding: 12px; text-align: right; width: 80px;">単価</th>
                        <th style="padding: 12px; text-align: center; width: 60px;">数量</th>
                        <th style="padding: 12px; text-align: right; width: 100px;">金額</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
                <tfoot>
                    <tr style="background: #f8f9fa;">
                        <td colspan="4" style="padding: 15px; text-align: right; font-weight: bold; font-size: 16px;">合計</td>
                        <td style="padding: 15px; text-align: right; font-weight: bold; font-size: 18px; color: #1A237E;">¥{total:,}</td>
                    </tr>
                </tfoot>
            </table>
        </div>
        
        <div style="padding: 20px; border: 1px solid #eee; border-top: none; background: #fff;">
            <h3 style="margin: 0 0 10px 0; color: #1A237E; font-size: 14px;">■ 備考 (Notes)</h3>
            <p style="margin: 0; color: #333; white-space: pre-wrap;">{note_content}</p>
        </div>
        
        <div style="background: #f8f9fa; padding: 20px; border: 1px solid #eee; border-top: none; border-radius: 0 0 12px 12px;">
            <p style="margin: 0; color: #666;">よろしくお願いいたします。</p>
            <p style="margin: 10px 0 0 0; color: #999; font-size: 12px;">
                このメールは ReplenMobile から自動送信されています。
            </p>
        </div>
    </body>
    </html>
    """
    return html


def generate_order_text(
    items: List[OrderItem],
    supplier_name: Optional[str] = None,
    note: Optional[str] = None,
) -> str:
    """
    Generate plain text email body for the order.
    """
    from datetime import datetime
    
    today = datetime.now().strftime("%Y年%m月%d日")
    total = sum(item.price * item.quantity for item in items)
    note_content = note.strip() if note and note.strip() else "特になし"
    
    lines = [
        "=" * 40,
        "注文書",
        "=" * 40,
        f"日付: {today}",
    ]
    
    if supplier_name:
        lines.append(f"宛先: {supplier_name} 御中")
    
    lines.append("")
    lines.append("-" * 40)
    
    for i, item in enumerate(items, 1):
        subtotal = item.price * item.quantity
        lines.append(f"{i}. {item.name}")
        lines.append(f"   ¥{item.price:,} × {item.quantity} = ¥{subtotal:,}")
    
    lines.append("-" * 40)
    lines.append(f"合計: ¥{total:,}")
    lines.append("")
    lines.append("-" * 40)
    lines.append("■ 備考 (Notes)")
    lines.append(note_content)
    lines.append("-" * 40)
    lines.append("")
    lines.append("よろしくお願いいたします。")
    lines.append("")
    lines.append("---")
    lines.append("ReplenMobile より自動送信")
    
    return "\n".join(lines)


def send_email_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    pdf_attachment: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
) -> EmailSendResult:
    """
    Send email using SMTP.
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return EmailSendResult(
            success=True,
            message="[DEV MODE] メール送信をシミュレートしました",
            confirmation_id=f"DEV-EMAIL-{uuid.uuid4().hex[:8].upper()}"
        )
    
    try:
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL or SMTP_USERNAME}>"
        msg["To"] = to_email
        
        # Attach text and HTML parts
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        
        # Attach PDF if provided
        if pdf_attachment and pdf_filename:
            pdf_part = MIMEApplication(pdf_attachment, Name=pdf_filename)
            pdf_part["Content-Disposition"] = f'attachment; filename="{pdf_filename}"'
            msg.attach(pdf_part)
        
        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        confirmation_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"
        return EmailSendResult(
            success=True,
            message="メールを送信しました",
            confirmation_id=confirmation_id
        )
        
    except smtplib.SMTPAuthenticationError:
        return EmailSendResult(
            success=False,
            message="メール認証に失敗しました。SMTP設定を確認してください。"
        )
    except smtplib.SMTPException as e:
        return EmailSendResult(
            success=False,
            message=f"メール送信エラー: {str(e)}"
        )
    except Exception as e:
        return EmailSendResult(
            success=False,
            message=f"予期しないエラー: {str(e)}"
        )


async def send_email_resend(
    to_email: str,
    subject: str,
    html_body: str,
    pdf_attachment: Optional[bytes] = None,
    pdf_filename: Optional[str] = None,
) -> EmailSendResult:
    """
    Send email using Resend API (alternative to SMTP).
    """
    if not RESEND_API_KEY:
        return EmailSendResult(
            success=True,
            message="[DEV MODE] メール送信をシミュレートしました",
            confirmation_id=f"DEV-EMAIL-{uuid.uuid4().hex[:8].upper()}"
        )
    
    try:
        import base64
        
        payload = {
            "from": RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        
        # Add attachment if provided
        if pdf_attachment and pdf_filename:
            payload["attachments"] = [{
                "filename": pdf_filename,
                "content": base64.b64encode(pdf_attachment).decode()
            }]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                return EmailSendResult(
                    success=True,
                    message="メールを送信しました",
                    confirmation_id=data.get("id")
                )
            else:
                return EmailSendResult(
                    success=False,
                    message=f"Resend API エラー: {response.text}"
                )
                
    except Exception as e:
        return EmailSendResult(
            success=False,
            message=f"メール送信エラー: {str(e)}"
        )


async def send_order_email(
    to_email: str,
    items: List[OrderItem],
    supplier_name: Optional[str] = None,
    pdf_path: Optional[str] = None,
    note: Optional[str] = None,
) -> EmailSendResult:
    """
    Send order via email with optional PDF attachment.
    
    Args:
        to_email: Recipient email address
        items: List of order items
        supplier_name: Name of the supplier
        pdf_path: Optional path to PDF file to attach
        note: Optional user memo (備考)
    
    Returns:
        EmailSendResult with success status
    """
    subject = f"【注文書】{supplier_name or 'ReplenMobile'} 宛"
    html_body = generate_order_html(items, supplier_name, note)
    text_body = generate_order_text(items, supplier_name, note)
    
    # Read PDF if provided
    pdf_attachment = None
    pdf_filename = None
    if pdf_path:
        try:
            with open(pdf_path, "rb") as f:
                pdf_attachment = f.read()
            pdf_filename = f"order_{supplier_name or 'order'}.pdf"
        except Exception:
            pass  # Continue without attachment
    
    # Try Resend first, fall back to SMTP
    if RESEND_API_KEY:
        return await send_email_resend(to_email, subject, html_body, pdf_attachment, pdf_filename)
    else:
        return send_email_smtp(to_email, subject, html_body, text_body, pdf_attachment, pdf_filename)
