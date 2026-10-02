# 城市洪涝应对指挥中心 —— 一体化镜像：后端 API + PostGIS 数据库（syq-pipe 已恢复在镜像里）
#
# 构建上下文 = 服务器 /syq/flood-aio/：src/ sql/ requirements.txt db/syq-pipe.dump entrypoint.sh
# 数据目录（DEM、批算 CSV、仿真成果）不进镜像，运行时目录映射到 /app/data。
#
# 基础：local/postgis:16.11-postgis3.6-pgrouting（Debian 12，与线上 postgis16 同版本，库里用到 pgrouting/vector 等扩展）。
# Python 3.14 从官方 python:3.14-slim-bookworm 整目录搬过来（同为 bookworm，glibc 一致）。

ARG PG_BASE=local/postgis:16.11-postgis3.6-pgrouting

# ---------- ① Python 依赖 ----------
FROM python:3.14-slim-bookworm AS pybuild
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install \
      --only-binary=rasterio,pandas,numpy,scipy,psycopg-binary,uvloop,httptools,watchfiles,websockets,pyyaml \
      -r requirements.txt

# ---------- ② 造一份已恢复好数据的 PGDATA 种子 ----------
FROM ${PG_BASE} AS dbseed
COPY db/syq-pipe.dump /tmp/syq-pipe.dump
# 跳过 vector（pgvector）扩展：基础镜像没装，库里没有任何列/索引用它（已核对）。
# 种子集群只在构建期用，本地 trust；postgres 口令在最终镜像 ENV PIPE_DB_PASSWORD 里写死，启动时同步。
RUN set -eux; \
    install -d -o postgres -g postgres /opt/pgseed; \
    gosu postgres initdb -D /opt/pgseed -U postgres --encoding=UTF8 --locale=en_US.utf8 --auth-local=trust --auth-host=trust; \
    gosu postgres pg_ctl -D /opt/pgseed -w -o "-c listen_addresses='' -c fsync=off -c synchronous_commit=off -c max_wal_size=4GB" start; \
    gosu postgres createdb -U postgres syq-pipe; \
    pg_restore -l /tmp/syq-pipe.dump | grep -vE ' EXTENSION - vector| COMMENT - EXTENSION vector' > /tmp/restore.list; \
    gosu postgres pg_restore -U postgres -d syq-pipe --no-owner -j 4 -L /tmp/restore.list /tmp/syq-pipe.dump; \
    gosu postgres psql -U postgres -d syq-pipe -Atc "select count(*) from simulation.run"; \
    gosu postgres psql -U postgres -d syq-pipe -c "vacuum analyze" ; \
    gosu postgres pg_ctl -D /opt/pgseed -m fast -w stop; \
    rm -f /tmp/syq-pipe.dump

# ---------- ③ 最终镜像 ----------
FROM ${PG_BASE}
COPY --from=pybuild /usr/local /usr/local
COPY --from=pybuild /opt/venv /opt/venv
# python 官方镜像里的运行时依赖；rasterio 的 GDAL 需要 libexpat.so.1，缺了会让 registry.py 静默退回 Zone B
RUN apt-get update \
 && apt-get install -y --no-install-recommends libexpat1 libffi8 libsqlite3-0 libbz2-1.0 liblzma5 zlib1g libuuid1 tini \
 && rm -rf /var/lib/apt/lists/* \
 && ldconfig \
 && /opt/venv/bin/python -c "import rasterio, scipy, pandas, psycopg, ssl, sqlite3; print('py ok')"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PGDATA=/var/lib/postgresql/data \
    PIPE_DB_HOST=127.0.0.1 PIPE_DB_PORT=5432 PIPE_DB_NAME=syq-pipe \
    PIPE_DB_SCHEMA=dmt_irrigationstormwater_abudhabi PIPE_DB_USER=postgres \
    PIPE_DB_PASSWORD="freedo"

# 已恢复好的库放在镜像里（种子）；PGDATA 为空时（首次启动 / 映射了空目录）由入口脚本复制过去
COPY --from=dbseed /opt/pgseed /opt/pgseed
WORKDIR /app
COPY src/ ./src/
COPY sql/ ./sql/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && useradd --system --create-home --uid 10001 app \
 && mkdir -p /app/data/processed/sim_ponding \
 && chown -R app /app/data/processed/sim_ponding

EXPOSE 8101 5432
VOLUME ["/var/lib/postgresql/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8101/', timeout=4).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
