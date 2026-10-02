# 一体化镜像 flood-aio（后端 API + PostGIS 数据库）

一个容器里跑两样：PostgreSQL 16 / PostGIS 3.6 / pgrouting（`syq-pipe` 库已恢复在镜像里）和后端 API（8101）。
API 连容器内的 127.0.0.1:5432，不依赖外部库。库快照时间 = 镜像构建时（2026-09-30，simulation.run 最新 id 837）。

## 目录映射（宿主机 → 容器）
| 宿主机 | 容器 | 权限 | 说明 |
|---|---|---|---|
| `./data` | `/app/data` | 只读 | 数据目录：DEM、processed 批算 CSV、sim_deliveries 仿真成果。源头 `/syq/flood-backend/data`（约 19 GB，不含 `temp*/` 原始交付） |
| `./cache/sim_ponding` | `/app/data/processed/sim_ponding` | 可写 | 溢水点缓存，首次查询现算后落盘 |
| `./pgdata` | `/var/lib/postgresql/data` | 可写 | 数据库文件。空目录首次启动自动用镜像里已恢复的库填充，之后所有写入落在这里；不映射则随容器丢 |

## 部署步骤（目标服务器需 docker）
```bash
gunzip -c flood-aio_latest.tar.gz | docker load
rsync -a <源>:/syq/flood-backend/data/ ./data/   # 数据目录（排除 temp*/ 与 al-bateen 的 zip 可省空间）
./run.sh                                  # 或 docker compose up -d
curl http://127.0.0.1:8101/               # 探活；文档 /docs
```
端口：API `8101`，数据库 `35433`（对外只想开 API 就删掉 `-p 35433:5432`）。数据库用户 `postgres`，口令已写死在镜像 ENV `PIPE_DB_PASSWORD` 里（与 backend/.env 一致），每次启动同步；`-e PIPE_DB_PASSWORD=...` 可覆盖。镜像里能看到口令，别推到公共仓库。

## 要点
- 升级镜像：`docker rm -f flood-aio` 后用新镜像再 `./run.sh`；`./pgdata` 里已有库会原样沿用，**不会**被新镜像种子覆盖。要回到镜像自带的库：停容器，清空 `./pgdata`，再起。
- `SIM_MOCK_PROGRESS` 默认 1（仿真进度模拟）；接真实算力侧后设 0。
- 未装 pgvector 扩展（源库装了但没有任何列/索引使用），其余扩展 postgis / pgrouting / postgres_fdw / pgcrypto / pg_trgm / ltree / uuid-ossp 齐全。
- 镜像约 10.9 GB（库 5.7 GB 是种子，另有 5.7 GB 在你映射的 pgdata 里首次展开一份）。
- 重建镜像：`/syq/flood-aio/`（Dockerfile、entrypoint.sh、src、sql、db/syq-pipe.dump）→ `docker build -t flood-aio:latest .`；换库快照就重做 `pg_dump -Fc` 覆盖 db/syq-pipe.dump。
