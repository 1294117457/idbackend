FROM minio/minio:latest

# 创建数据目录
RUN mkdir -p /data && chown minio-user:minio-user /data

EXPOSE 9000 9001

ENV MINIO_ROOT_USER=zhouch
ENV MINIO_ROOT_PASSWORD=zhouchenhui

VOLUME ["/data"]

CMD ["server", "/data", "--console-address", ":9001"]
