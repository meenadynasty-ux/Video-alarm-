FROM python:3.11-slim

# FFmpeg इंस्टॉल करें ताकि हर प्लेटफॉर्म के वीडियो में 100% आवाज़ (Audio+Video) साथ आए
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp

COPY app.py .

# टेम्परेरी मीडिया फोल्डर बनाएं
RUN mkdir -p /app/temp_alarm_media

ENV PORT=5000
EXPOSE 5000

# 1 वर्कर और 4 थ्रेड्स ताकि VIDEO_PROCESS_LOCK एक बार में एक ही वीडियो को सुरक्षित रूप से प्रोसेस करे
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "180", "app:app"]
