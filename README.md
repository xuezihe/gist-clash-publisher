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
cp config/gist-sub.env.example /etc/gist-sub.env
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

部署（推荐路径）
--------------
1) 克隆仓库：

```bash
git clone https://github.com/xuezihe/gist-clash-publisher
cd gist-clash-publisher
```

2) 部署脚本到目标路径：

```bash
sudo mkdir -p /opt/gist-sub
sudo cp src/fetch_gist.py /opt/gist-sub/
sudo chmod +x /opt/gist-sub/fetch_gist.py
```

3) 配置 systemd 定时器：

```bash
./scripts/generate_timer.sh /etc/gist-sub.env /etc/systemd/system/gist-sub.timer
sudo cp config/systemd/gist-sub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gist-sub.timer
```

4) 配置静态服务（Caddy 或 Nginx）

推荐 Caddy（自动 HTTPS）：

```bash
sudo apt install -y caddy
sudo cp config/caddy/Caddyfile.example /etc/caddy/Caddyfile
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

5) HTTPS
- Caddy 自动签发证书
- Nginx 需要自行配置 certbot

安全建议
--------
- Basic Auth 必须在 HTTPS 下使用
- URL 中包含用户名密码可能出现在日志中，注意访问日志与代理配置

更多设计与后续路线
------------------
- 需求与设计：`memory-bank/prd.md`
- 实现计划：`memory-bank/03-Implementation-Plan.md`
- 上线检查清单：`memory-bank/04-MVP-Launch-Checklist.md`
