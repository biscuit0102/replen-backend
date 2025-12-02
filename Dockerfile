FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    fonts-ipafont-gothic \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create fonts directory and copy Japanese font
RUN mkdir -p fonts && \
    cp /usr/share/fonts/truetype/fonts-japanese-gothic.ttf fonts/ipaexg.ttf || true

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
