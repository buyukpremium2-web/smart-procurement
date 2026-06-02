FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend
COPY . .

# frontend/ papkasi backend/ bilan bir xil darajada bo'lsa
# Railway build context faqat backend/ — shuning uchun
# index.html ni backend/static/ ga qo'yish kerak
RUN mkdir -p /app/frontend/src

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
