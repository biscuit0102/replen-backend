# Backend Deployment Guide

## Required Environment Variables

### ✅ REQUIRED (App will not start without these)
```bash
OPENAI_API_KEY=sk-your-key          # For AI invoice parsing
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key  # For analytics (optional: SUPABASE_ANON_KEY)
```

### ⚠️ RECOMMENDED (Features will be degraded without these)
```bash
# Barcode Lookup
YAHOO_API_KEY=your-key              # Without this, mock data will be returned

# FAX Sending
CLICKSEND_USERNAME=your-username
CLICKSEND_API_KEY=your-key
FAX_FROM_NUMBER=+81312345678

# Email Sending (Option 1: SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=orders@replen.app
SMTP_FROM_NAME=ReplenMobile

# Email Sending (Option 2: Resend API - recommended)
RESEND_API_KEY=re_your-key
RESEND_FROM_EMAIL=orders@yourdomain.com
```

### 🔒 SECURITY
```bash
ENVIRONMENT=production              # Set to 'production' for strict CORS
```

## Installation

1. Install dependencies:
```bash
cd backend
pip install -r requirements.txt
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your actual keys
```

3. Run the server:
```bash
uvicorn main:app --reload
```

## Rate Limits

The following rate limits are enforced per IP address:

- `/api/parse-invoice` - **10 requests/minute** (expensive AI calls)
- `/api/lookup/{barcode}` - **30 requests/minute** (Yahoo API calls)
- `/api/send-order` - **20 requests/hour** (FAX/Email sending)
- `/api/send-order-multi` - **20 requests/hour** (Multi-channel sending)

## Logging

All endpoints now use structured logging:
- INFO: Successful operations
- WARNING: Missing optional config
- ERROR: Failed operations with stack traces

Logs are printed to stdout in format:
```
2026-01-03 22:00:00 - main - INFO - ✅ Environment validation passed
```

## Health Check

Check backend status:
```bash
curl https://your-backend.com/health
```

Response:
```json
{
  "status": "healthy",
  "services": {
    "openai": true,
    "yahoo": true,
    "clicksend": true,
    "email_smtp": false,
    "email_resend": true
  }
}
```

## Deployment to Railway

1. Push to GitHub
2. Connect Railway to your repo
3. Add environment variables in Railway dashboard
4. Deploy!

Railway will automatically:
- Install dependencies from requirements.txt
- Run the FastAPI app
- Handle SSL/HTTPS
- Provide a public URL

## Troubleshooting

### "Missing required environment variables" error
- Check that OPENAI_API_KEY and SUPABASE_URL are set
- Verify no typos in variable names

### Rate limit errors (429)
- Users are hitting rate limits
- Consider upgrading limits for trusted users
- Or implement user-based rate limiting with auth tokens

### No logs showing
- Check that logging is configured
- Railway: Check "Logs" tab in dashboard
