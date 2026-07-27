FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --timeout 300

COPY . .

ENV PYTHONPATH=/app

# 启动流程：uvicorn 直接启动 main:app，支持 --workers 多进程。
# schema 同步在 main.py 启动时自动完成（幂等）。
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]	
