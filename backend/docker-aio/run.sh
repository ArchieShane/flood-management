#!/usr/bin/env bash
# 在目标服务器上起一体化容器（不用 compose 时）。目录映射：
#   ./data              → /app/data                   只读  数据目录
#   ./cache/sim_ponding → /app/data/processed/sim_ponding  可写  溢水点缓存
#   ./pgdata            → /var/lib/postgresql/data    可写  数据库文件（首次自动从镜像种子填充）
# 用法：  ./run.sh [标签]      需要同目录 .env（PIPE_DB_PASSWORD=...）
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TAG="${1:-latest}"; NAME="${NAME:-flood-aio}"
API_PORT="${API_PORT:-8101}"; DB_PORT="${DB_PORT:-35433}"
DATA_DIR="${DATA_DIR:-$PWD/data}"; CACHE_DIR="${CACHE_DIR:-$PWD/cache/sim_ponding}"; PGDATA_DIR="${PGDATA_DIR:-$PWD/pgdata}"

ENVARG=(); [ -f .env ] && ENVARG=(--env-file .env)
[ -f "$DATA_DIR/processed/hotspots_845.csv" ] || { echo "数据目录不完整：$DATA_DIR/processed/hotspots_845.csv 不存在" >&2; exit 1; }
mkdir -p "$CACHE_DIR" "$PGDATA_DIR"
# 容器里 API 以 uid 10001 运行：数据全局可读，缓存目录归它
find "$DATA_DIR" \( -type d ! -perm -o=rx -o -type f ! -perm -o=r \) -exec chmod a+rX {} + 2>/dev/null || true
chown 10001 "$CACHE_DIR"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  -p "${API_PORT}:8101" -p "${DB_PORT}:5432" \
  "${ENVARG[@]}" \
  -v "$DATA_DIR:/app/data:ro" \
  -v "$CACHE_DIR:/app/data/processed/sim_ponding" \
  -v "$PGDATA_DIR:/var/lib/postgresql/data" \
  "flood-aio:${TAG}"
echo "已启动 $NAME，API http://127.0.0.1:${API_PORT}/  文档 /docs ；首次启动需要 20–60 秒复制数据库种子。"
