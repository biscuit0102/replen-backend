FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (Japanese fonts for PDF generation)
RUN apt-get update && apt-get install -y \
    fonts-ipafont-gothic \
    fonts-ipafont-mincho \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create fonts directory and copy Japanese font (try multiple paths)
RUN mkdir -p fonts && \
    (cp /usr/share/fonts/opentype/ipafont-gothic/ipag.ttf fonts/ipaexg.ttf 2>/dev/null || \
     cp /usr/share/fonts/truetype/ipafont-gothic/ipag.ttf fonts/ipaexg.ttf 2>/dev/null || \
     echo "Font not found, will use fallback")

# Railway sets PORT env variable dynamically
# Don't set a default - Railway will provide it

# Run the application
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
