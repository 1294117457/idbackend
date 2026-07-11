FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --timeout 300

COPY . .

ENV PYTHONPATH=/app

# 启动流程：src.main() 内部先调 Base.metadata.create_all（幂等同步 schema），
# 再起 uvicorn serve。无需 alembic / 不用版本表。
# 详细设计见 docs/base/db-schema-sync.md。
CMD ["python", "-m", "src.main"]
