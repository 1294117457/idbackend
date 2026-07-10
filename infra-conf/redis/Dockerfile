FROM redis:7-alpine

# 创建数据目录
RUN mkdir -p /data && chown redis:redis /data

EXPOSE 6379

VOLUME ["/data"]

CMD ["redis-server", "--requirepass", "zhouchenhui", "--appendonly", "yes"]
