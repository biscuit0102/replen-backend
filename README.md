# ReplenMobile Backend

AI-powered B2B ordering backend for Japanese businesses.

## Features

- 🤖 **AI Invoice Parsing** - GPT-4o Vision extracts products from invoice images
- 🔍 **Barcode Lookup** - Yahoo Japan Shopping API for product information
- 📠 **Multi-Channel Order Sending**:
  - **FAX** - ClickSend API for traditional fax delivery
  - **Email** - SMTP or Resend API for email orders
  - **LINE** - LINE Messaging API for instant messaging

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file with the following:

```bash
# OpenAI (Required for invoice parsing)
OPENAI_API_KEY=sk-your-key

# Yahoo Japan API (Required for barcode lookup)
YAHOO_API_KEY=your-key

# ClickSend (Required for FAX)
CLICKSEND_USERNAME=your-username
CLICKSEND_API_KEY=your-api-key
FAX_FROM_NUMBER=+81312345678

# Email - Option 1: SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=orders@replen.app
EMAIL_FROM_NAME=ReplenMobile

# Email - Option 2: Resend API (recommended)
RESEND_API_KEY=re_your-key

# LINE Messaging API
LINE_CHANNEL_ACCESS_TOKEN=your-channel-access-token
LINE_CHANNEL_SECRET=your-channel-secret

# Development mode (set to true to simulate sending)
DEV_MODE=true
```

### 3. Run Development Server

```bash
uvicorn main:app --reload
```

Server will start at `http://localhost:8000`

### 4. API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### `POST /api/parse-invoice`
Parse an invoice image using AI.

```json
{
  "base64_image": "data:image/jpeg;base64,..."
}
```

### `GET /api/lookup/{barcode}`
Lookup product by JAN barcode.

### `POST /api/send-order` (Legacy - FAX only)
Send order via fax.

```json
{
  "items": [{"name": "商品名", "price": 1000, "quantity": 2}],
  "supplier_fax": "+81312345678",
  "supplier_name": "やまや"
}
```

### `POST /api/send-order-multi` (Recommended)
Send order via FAX, Email, or LINE based on contact_method.

```json
{
  "items": [{"name": "商品名", "price": 1000, "quantity": 2}],
  "supplier_name": "やまや",
  "contact_method": "email",
  "email": "order@supplier.co.jp"
}
```

Supported contact methods:
- `"fax"` - Requires `fax_number`
- `"email"` - Requires `email`
- `"line"` - Requires `line_id`

## Deployment (Render.com)

1. Connect your GitHub repository
2. Set environment variables in Render dashboard
3. Deploy as Docker container

## Required API Keys

| Service | Purpose | Get from |
|---------|---------|----------|
| OpenAI | Invoice AI parsing | https://platform.openai.com/ |
| Yahoo Japan | Barcode lookup | https://e.developer.yahoo.co.jp/ |
| ClickSend | FAX sending | https://clicksend.com/ |
| Resend | Email sending | https://resend.com/ |
| LINE | LINE messaging | https://developers.line.biz/
# Trigger redeploy Wed Dec  3 14:02:41 JST 2025
