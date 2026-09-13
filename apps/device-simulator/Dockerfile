FROM python:3.11.9-slim
RUN useradd --create-home --uid 10001 simulator
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY src/ ./src/
USER simulator
ENV PYTHONUNBUFFERED=1
CMD ["python", "src/main.py"]
