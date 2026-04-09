# web-diagnostic Docker 部署（JumpServer 主机）

设计说明见仓库内 spec：`docs/superpowers/specs/2026-03-23-jump-server-docker-web-diagnostic-design.md`。

## 构建

在 **仓库根目录**（含 `web-diagnostic/`、`tools/log-analyzer/`、`.ai-config/`、`.mcp.json`）执行：

```bash
docker build -f web-diagnostic/Dockerfile -t web-diagnostic:mvp .
```

## 本地运行

```bash
docker run --rm -p 8080:8080 web-diagnostic:mvp
curl -sSf http://127.0.0.1:8080/health
```

浏览器访问：`http://127.0.0.1:8080/`。

## 跳板机后台运行示例

登录运维主机（示例：`ssh libi.lin@jumpserver.tuya-inc.top -p33022`）后：

```bash
docker run -d --name web-diagnostic --restart unless-stopped -p 8080:8080 web-diagnostic:mvp
```

将 `8080:8080` 左侧改为宿主机希望暴露的端口；若需只监听某张内网网卡，使用 `-p <内网IP>:8080:8080`（视 Docker 版本与系统而定）。

## 镜像分发

- **离线：** `docker save web-diagnostic:mvp -o web-diagnostic-mvp.tar`，拷贝到主机后 `docker load -i web-diagnostic-mvp.tar`。
- **内网仓库：** `docker tag` / `docker push` 到公司 registry，主机上 `docker pull`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `WORKSPACE_ROOT` | 仓库根路径；镜像内默认 `/workspace`。 |
| `PROJECT_ROOT` | MCP `run.sh` 使用；镜像内默认 `/workspace`（不依赖容器内 `.git`）。 |
| `WEB_DIAGNOSTIC_SKIP_CLAUDE` | 默认 `1`：不探测 `claude` CLI，诊断对话不可用但服务可启动。若主机已安装 Claude 且需启用，设为 `0` 并自行处理出网与许可。 |

## 持久化（非 MVP）

上传与历史默认写在容器内；需要保留时增加 volume，例如：

```text
-v web_diag_data:/workspace/.ai-config/tools/log-analyzer/data
-v web_diag_hist:/workspace/web-diagnostic/data/history
```

路径以实际部署为准。

## 回滚

保留旧 tag 的镜像；`docker stop web-diagnostic && docker rm web-diagnostic` 后，用旧镜像 tag 再 `docker run`。
