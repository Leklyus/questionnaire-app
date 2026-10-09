FROM python:3.12-slim

WORKDIR /app

COPY app.py .
COPY static ./static

EXPOSE 8000

CMD ["python3", "app.py"]
