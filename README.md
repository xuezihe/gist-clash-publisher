gist-clash-publisher
====================

一个可部署在 Debian 12 的小工具：定时从 GitHub Gist 拉取订阅文件，原子写入到 Web 根目录，并通过 Caddy/Nginx + Basic Auth 暴露为固定订阅 URL。

功能概览
--------
- 定时拉取 Gist（支持 private gist，支持 ETag 增量）
- 原子写入到 `/var/www/sub/<PATH_TOKEN>/proxies.yaml`
- Basic Auth + HTTPS 对外提供订阅
- 预留模块化扩展点（内容校验 / 状态落盘 / 多租户）

目录结构
--------
- `src/fetch_gist.py`：主脚本
- `src/lib/`：占位模块（validators/status/registry）
- `config/gist-sub.env.example`：环境变量示例
- `config/systemd/`：systemd service/timer 模板
- `config/caddy/`、`config/nginx/`：静态服务配置模板

环境与依赖
----------
- Python 3.9+（标准库即可）
- 运行时网络可访问 GitHub API

配置环境变量
------------
复制示例配置并修改：

```bash
sudo cp config/gist-sub.env.example /etc/gist-sub.env
sudo chmod 600 /etc/gist-sub.env
sudo nano /etc/gist-sub.env
```

必须配置：
- `GIST_ID`
- `PATH_TOKEN`
- `OUTPUT_BASE`
- `OUTPUT_NAME`

可选：
- `GIST_FILE`
- `GITHUB_TOKEN`（private gist 必填）

本地运行（验证）
---------------
```bash
set -a; source /etc/gist-sub.env; set +a
python3 src/fetch_gist.py
```

状态与日志（F2）
---------------
- 状态文件：`/var/www/sub/<PATH_TOKEN>/status.json`
- 字段包含：`last_attempt_ts`、`last_success_ts`、`status`、`last_error`、`etag`、`sha256`、`bytes`、`duration_ms`
- 运行日志为 JSON 格式，systemd 下可用 `journalctl -u gist-sub.service` 查看

部署（推荐路径）
--------------
1) 克隆仓库：

```bash
sudo git clone https://github.com/xuezihe/gist-clash-publisher /opt/gist-clash-publisher
cd /opt/gist-clash-publisher
```

2) 配置环境变量：

```bash
sudo cp config/gist-sub.env.example /etc/gist-sub.env
sudo chmod 600 /etc/gist-sub.env
sudo nano /etc/gist-sub.env
```

3) 确认 systemd service 中的仓库路径与实际一致（默认 `/opt/gist-clash-publisher`）：

```bash
sudo cp config/systemd/gist-sub.service /etc/systemd/system/
```

4) 配置 systemd 定时器：

```bash
sh ./scripts/generate_timer.sh /etc/gist-sub.env /etc/systemd/system/gist-sub.timer
sudo systemctl daemon-reload
sudo systemctl enable --now gist-sub.timer
```

`gist-sub.service` 已内置日志限速（systemd rate limit），如需调整可修改 `LogRateLimitIntervalSec` 与 `LogRateLimitBurst`。

5) 配置静态服务（Caddy 或 Nginx）

推荐 Caddy（自动 HTTPS）：

```bash
sudo apt install -y caddy
```

设置 Caddy Basic Auth 账号密码：

```bash
caddy hash-password --plaintext '你的密码'
```

把生成的 hash 填入 `/etc/caddy/Caddyfile` 的 `basicauth` 块中，并设置你的用户名：

```
basicauth @sub {
    user <hash>
}
```

也可以用脚本生成账号/密码/订阅 URL，并保存到服务器上的 Markdown 文件，同时生成 Caddyfile 到项目内：

```bash
sh ./scripts/generate_caddy_credentials.sh example.com
```

默认会读取 `/etc/gist-sub.env`，保存到 `/etc/gist-sub-credentials.md`（包含明文密码，权限为 600），并写入 `config/caddy/Caddyfile.generated`。

打开 `/etc/gist-sub-credentials.md` 获取订阅 URL，复制生成的 Caddyfile，再 reload Caddy：

```bash
sudo cp config/caddy/Caddyfile.generated /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Nginx 方案：

```bash
sudo apt install -y nginx apache2-utils
sudo cp config/nginx/sub.example.com /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/sub.example.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

6) HTTPS
- Caddy 自动签发证书
- Nginx 需要自行配置 certbot

订阅 URL
--------
订阅地址由域名（或 IP）+ 随机路径 + 文件名组成：

```
https://<user>:<pass>@<host>/<PATH_TOKEN>/<OUTPUT_NAME>
```

示例：
```
https://user:pass@sub.example.com/a1b2c3d4e5f6/proxies.yaml
```

其中：
- `PATH_TOKEN` 来自 `/etc/gist-sub.env`
- `OUTPUT_NAME` 来自 `/etc/gist-sub.env`
- `<host>` 来自 Caddy/Nginx 的站点配置
使用脚本生成账号时，订阅 URL 会写入 `/etc/gist-sub-credentials.md`。

安全建议
--------
- Basic Auth 必须在 HTTPS 下使用
- URL 中包含用户名密码可能出现在日志中，注意访问日志与代理配置
- 如果只用 IP，公有 CA 通常无法签发证书；可用域名、或自签证书并在客户端信任
