FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 libdmtx0b libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HF Spaces runs the container as a non-root user; EasyOCR caches its
# models under $HOME, so point HOME somewhere writable.
ENV HOME=/tmp

EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
