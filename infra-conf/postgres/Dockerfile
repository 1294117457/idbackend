FROM postgres:16

# 创建数据目录
RUN mkdir -p /var/lib/postgresql/data && \
    chown -R postgres:postgres /var/lib/postgresql/data && \
    chmod 700 /var/lib/postgresql/data

ENV POSTGRES_USER=zhouch
ENV POSTGRES_PASSWORD=zhouchenhui
ENV POSTGRES_DB=iddata

EXPOSE 5432

CMD ["postgres"]
