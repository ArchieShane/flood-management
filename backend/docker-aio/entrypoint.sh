#!/bin/bash
# 一体化容器入口：PostgreSQL（后台）→ 等就绪 → uvicorn（API）。任一进程退出则整体退出，由 docker 重启策略拉起。
set -euo pipefail

: "${PIPE_DB_PASSWORD:?镜像未内置数据库口令}"   # 镜像 ENV 已内置；-e 可覆盖

PGDATA="${PGDATA:-/var/lib/postgresql/data}"
mkdir -p "$PGDATA"

# 1) PGDATA 为空 → 用镜像里的种子（syq-pipe 已恢复）初始化；已有数据就原样使用，绝不覆盖
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  if [ -n "$(ls -A "$PGDATA" 2>/dev/null | grep -v '^lost+found$' || true)" ]; then
    echo "[entrypoint] $PGDATA 非空但不是 PG 数据目录，拒绝覆盖。" >&2; exit 1
  fi
  echo "[entrypoint] 首次启动：从镜像种子初始化 PGDATA ..."
  cp -a /opt/pgseed/. "$PGDATA"/
fi
chown -R postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"

# 2) 连接策略：本机 trust（仅用于下面设口令），网络一律口令；种子里 pg_hba 是构建期的 trust，每次启动重写
cat > "$PGDATA/pg_hba.conf" <<HBA
local   all all                trust
host    all all 127.0.0.1/32   scram-sha-256
host    all all ::1/128        scram-sha-256
host    all all 0.0.0.0/0      scram-sha-256
HBA

PG_OPTS=(-c listen_addresses='*' -c port=5432
         -c shared_buffers="${PG_SHARED_BUFFERS:-512MB}" -c max_connections="${PG_MAX_CONNECTIONS:-100}")

gosu postgres postgres -D "$PGDATA" "${PG_OPTS[@]}" &
PG_PID=$!

for _ in $(seq 1 120); do
  gosu postgres pg_isready -q -h /var/run/postgresql -p 5432 && break
  kill -0 "$PG_PID" 2>/dev/null || { echo "[entrypoint] postgres 意外退出" >&2; exit 1; }
  sleep 1
done

# 3) 每次启动把口令同步为环境变量（scram）；用 psql 变量避免口令里的引号出事
echo "ALTER ROLE postgres PASSWORD :'pw'" | gosu postgres psql -h /var/run/postgresql -U postgres -d postgres \
  -v ON_ERROR_STOP=1 -v pw="$PIPE_DB_PASSWORD" -f - >/dev/null
echo "[entrypoint] 数据库就绪，启动 API ..."

# 4) API 以非 root 运行；数据目录只读挂载，读不到 DEM 时 registry 会静默退回 Zone B —— 先提示
[ -f /app/data/processed/hotspots_845.csv ] || echo "[entrypoint] 警告：/app/data 里没有 processed/hotspots_845.csv，数据目录是否已映射？" >&2
[ -d /app/data/DEM_UAE_UTM40 ] || echo "[entrypoint] 警告：缺 /app/data/DEM_UAE_UTM40，高程将静默退回 Zone B。" >&2

gosu app uvicorn stormwater.api.main:app --app-dir /app/src --host 0.0.0.0 --port 8101 &
API_PID=$!

term() { kill -TERM "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true
         kill -INT "$PG_PID" 2>/dev/null || true; wait "$PG_PID" 2>/dev/null || true; exit 0; }
trap term TERM INT

wait -n "$PG_PID" "$API_PID" || true
echo "[entrypoint] 有进程退出，容器结束" >&2
kill -TERM "$API_PID" 2>/dev/null || true
kill -INT "$PG_PID" 2>/dev/null || true
wait || true
exit 1
