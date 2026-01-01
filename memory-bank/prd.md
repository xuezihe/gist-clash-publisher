下面给你一套在 **Debian 12** 上很“工程化”、可维护且**模块化**的方案：**Python 定时拉取 GitHub Gist → 原子写入到 web root → 用 Nginx 或 Caddy 以 Basic Auth + 随机路径对外提供静态文件**。你后续在别处只需要订阅一个固定 URL（带用户名密码 + 随机路径）。

---

## 目标形态（你最终得到的东西）

* 外部访问（示例）
  `https://user:pass@sub.example.com/<随机路径>/proxies.yaml`

* 服务器内部结构（建议）

  * 脚本：`/opt/gist-sub/fetch_gist.py`
  * 配置：`/etc/gist-sub.env`
  * 输出目录（web root 下）：`/var/www/sub/<随机路径>/proxies.yaml`
  * 定时器：systemd timer（比 cron 更可控、可观测）

---

## 总体架构

1. **Fetcher（Python）**

   * 通过 GitHub API 拉取 gist 元数据（可选用 PAT，支持 private gist）
   * 定位你要的文件（按文件名或默认第一个）
   * 用 ETag / If-None-Match 做增量更新（没变就不写盘）
   * 将内容 **原子写入** 到目标路径（避免写一半被客户端拉到）

2. **Scheduler（systemd timer）**

   * 每 N 分钟运行一次 fetcher
   * 可以用 `journalctl` 直接看日志与错误

3. **Static server（Nginx 或 Caddy）**

   * 只提供静态文件
   * Basic Auth
   * HTTPS（Caddy 自动申请证书；Nginx 用 certbot 也行）
   * 禁止目录列表/只暴露你想暴露的路径

---

## 模块化设计（为后续功能预留清晰扩展点）

为了方便在 MVP 上线后按 `memory-bank/backlog.md` 逐步增强，建议从一开始就明确**模块边界**与**配置入口**：

### 目录结构（建议）

```
/opt/gist-sub/
  fetch_gist.py            # MVP 单文件脚本（后续可拆分模块）
  lib/                     # 后续扩展模块的容器（校验/多租户/状态落盘等）
    validators.py
    registry.py
    status.py
  templates/               # 过期占位/健康检查等模板
    expired_proxies.yaml
```

### 最小 lib/ 骨架（占位调用，不改变 MVP 逻辑）

在 MVP 阶段也可以先“预留模块位置”，保持主流程可读，并为后续 F1/F2 直接落位：

```
/opt/gist-sub/
  fetch_gist.py
  lib/
    validators.py
    registry.py
    status.py
```

`validators.py`（占位）：

```python
def validate_content(raw: bytes) -> tuple[bool, str]:
    # MVP: 仅占位，始终通过
    return True, ""
```

`status.py`（占位）：

```python
def record_status(status_path: str, payload: dict) -> None:
    # MVP: 仅占位，不落盘
    return None
```

`registry.py`（占位）：

```python
def load_registry(path: str) -> list[dict]:
    # MVP: 单实例时可以返回空或单条配置占位
    return []
```

`fetch_gist.py` 中的最小调用点（伪代码）：

```python
registry = load_registry("/etc/gist-sub.users.json")
# MVP 单租户时可忽略 registry，或 fallback 到 env 配置

ok, reason = validate_content(raw)
if not ok:
    record_status(status_path, {"status": "invalid", "reason": reason})
    return 1

record_status(status_path, {"status": "success", "bytes": len(raw)})
atomic_write(out_path, raw)
```

这样后续做 F1（内容校验）/F2（状态落盘）时，只需要替换 `validators.py` / `status.py` 的内部实现，不改主流程结构。

### 关键扩展点（对应 backlog 方向）

* **内容校验（F1）**：在写盘前加 `validate_content()`。
* **状态落盘（F2）**：统一由 `status.py` 管理 `status.json`。
* **多租户（F3）**：引入 `registry.py` 读取 `users.json/yaml`，对每个用户循环更新。
* **访问控制（F4）**：交给 Nginx/Caddy 层的 allowlist/geo 配置。

### 配置分层（可读性与可扩展性）

* **基础配置**：`/etc/gist-sub.env`（MVP）
* **多租户配置**：`/etc/gist-sub.users.json`（后续）
* **模板文件**：`/opt/gist-sub/templates/*`（后续）

> 这样每个新功能都能有“明确的落点”：要么是 `lib/` 的新模块，要么是 `/etc/` 的新配置，不会把逻辑塞进一个大脚本里难维护。

---

## 配置项（ENV 驱动，方便部署）

建议放到 `/etc/gist-sub.env`：

```bash
# GitHub
GIST_ID="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
GIST_FILE="proxies.yaml"          # gist 里对应文件名（可选，不填就取第一个）
GITHUB_TOKEN="ghp_..."            # 可选：private gist 必须；public gist 也建议配，避免限流

# 输出
OUTPUT_BASE="/var/www/sub"
PATH_TOKEN="a1b2c3d4e5f6..."       # 随机路径（建议固定，别每次变）
OUTPUT_NAME="proxies.yaml"

# 更新策略
INTERVAL_MINUTES="5"            # 单位是分钟
```

> `PATH_TOKEN` 你生成一次就固定下来：
> `openssl rand -hex 16`
> 然后把结果写进 env。这样订阅 URL 永远不变，但别人猜不到路径。

---

## Python 拉取脚本（可直接用）

保存为：`/opt/gist-sub/fetch_gist.py`

```python
#!/usr/bin/env python3
import os
import sys
import json
import time
import tempfile
import pathlib
import urllib.request
from urllib.error import HTTPError, URLError

def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if (v is not None and v != "") else default

def http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        status = resp.status
        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read()
        return status, resp_headers, body

def atomic_write(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False) as tf:
        tf.write(data)
        tf.flush()
        os.fsync(tf.fileno())
        tmp_name = tf.name
    os.replace(tmp_name, str(path))  # atomic on same filesystem

def main():
    gist_id = env("GIST_ID")
    if not gist_id:
        print("Missing GIST_ID", file=sys.stderr)
        return 2

    gist_file = env("GIST_FILE")  # optional
    token = env("GITHUB_TOKEN")   # optional but recommended

    output_base = pathlib.Path(env("OUTPUT_BASE", "/var/www/sub"))
    path_token = env("PATH_TOKEN")
    if not path_token:
        print("Missing PATH_TOKEN (generate once: openssl rand -hex 16)", file=sys.stderr)
        return 2

    output_name = env("OUTPUT_NAME", "proxies.yaml")
    out_path = output_base / path_token / output_name

    etag_path = out_path.with_suffix(out_path.suffix + ".etag")

    api_url = f"https://api.github.com/gists/{gist_id}"
    headers = {
        "User-Agent": "gist-sub-fetcher/1.0",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # If-None-Match for gist metadata (optional)
    if etag_path.exists():
        try:
            headers["If-None-Match"] = etag_path.read_text().strip()
        except Exception:
            pass

    try:
        status, resp_headers, body = http_get(api_url, headers)
    except HTTPError as e:
        if e.code == 304:
            print("No change (304) - skip")
            return 0
        print(f"HTTPError: {e.code} {e.reason}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1

    # Save new ETag (if present)
    new_etag = resp_headers.get("etag")
    if new_etag:
        atomic_write(etag_path, new_etag.encode("utf-8"))

    meta = json.loads(body.decode("utf-8"))
    files = meta.get("files", {})
    if not files:
        print("No files in gist", file=sys.stderr)
        return 1

    # pick file
    if gist_file:
        f = files.get(gist_file)
        if not f:
            print(f"GIST_FILE '{gist_file}' not found. Available: {list(files.keys())}", file=sys.stderr)
            return 1
    else:
        # first file
        f = next(iter(files.values()))

    raw_url = f.get("raw_url")
    if not raw_url:
        print("Missing raw_url in gist file metadata", file=sys.stderr)
        return 1

    # Download raw content (support private gist with Authorization header)
    raw_headers = {"User-Agent": "gist-sub-fetcher/1.0"}
    if token:
        raw_headers["Authorization"] = f"Bearer {token}"

    try:
        _, _, raw = http_get(raw_url, raw_headers)
    except Exception as e:
        print(f"Failed to download raw: {e}", file=sys.stderr)
        return 1

    # Optional: basic sanity check (avoid writing HTML error pages)
    if raw.lstrip().startswith(b"<!doctype html") or raw.lstrip().startswith(b"<html"):
        print("Raw looks like HTML; refusing to write (maybe auth/limit issue).", file=sys.stderr)
        return 1

    atomic_write(out_path, raw)
    print(f"Updated: {out_path} ({len(raw)} bytes)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

权限与目录：

```bash
sudo mkdir -p /opt/gist-sub
sudo nano /opt/gist-sub/fetch_gist.py
sudo chmod +x /opt/gist-sub/fetch_gist.py

sudo nano /etc/gist-sub.env
sudo chmod 600 /etc/gist-sub.env
```

手动试跑：

```bash
set -a; source /etc/gist-sub.env; set +a
sudo -E /opt/gist-sub/fetch_gist.py
```

---

## 定时更新（systemd service + timer）

`/etc/systemd/system/gist-sub.service`

```ini
[Unit]
Description=Fetch GitHub Gist and publish static subscription file
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/gist-sub.env
ExecStart=/opt/gist-sub/fetch_gist.py
User=root
```

`/etc/systemd/system/gist-sub.timer`

```ini
[Unit]
Description=Run gist-sub fetch periodically

[Timer]
OnBootSec=30
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gist-sub.timer
sudo systemctl list-timers | grep gist-sub
sudo journalctl -u gist-sub.service -n 50 --no-pager
```

---

## 对外提供：Nginx（Basic Auth + 随机路径）

1. 生成 htpasswd：

```bash
sudo apt update
sudo apt install -y nginx apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd user
# 输入密码
sudo chmod 640 /etc/nginx/.htpasswd
```

2. Nginx server 配置（示例 `/etc/nginx/sites-available/sub.example.com`）

> 把 `<随机路径>` 替换成你 env 的 `PATH_TOKEN`。

```nginx
server {
    listen 80;
    server_name sub.example.com;

    # 强烈建议：上线请配 HTTPS，这里先给 80 示例，实际用 443 + certbot
    root /var/www/sub;

    location = /<随机路径>/proxies.yaml {
        auth_basic "Subscription";
        auth_basic_user_file /etc/nginx/.htpasswd;

        default_type text/yaml;
        add_header Cache-Control "no-store";
        try_files /<随机路径>/proxies.yaml =404;
    }

    # 其他路径全部拒绝（减少暴露面）
    location / {
        return 404;
    }
}
```

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/sub.example.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

HTTPS（Nginx）建议用 certbot：`sudo apt install certbot python3-certbot-nginx` 然后 `sudo certbot --nginx -d sub.example.com`

---

## 对外提供：Caddy（更省事，自动 HTTPS）

`sudo apt install -y caddy`

`/etc/caddy/Caddyfile`：

```caddy
sub.example.com {
    @sub path /<随机路径>/proxies.yaml

    basicauth @sub {
        user JDJhJDE0JHc2Z3...  # 用 caddy hash-password 生成
    }

    root * /var/www/sub
    file_server

    handle {
        respond 404
    }
}
```

生成密码 hash：

```bash
caddy hash-password --plaintext '你的密码'
```

重载：

```bash
sudo systemctl reload caddy
```

---

## 安全要点（你这需求里最容易踩坑的）

1. **不要用 HTTP**：Basic Auth 明文可被抓包。务必 HTTPS。
2. **URL 带 user:pass 会泄漏在日志/历史记录/代理**：
   如果订阅端支持，优先用“普通 URL + 认证弹窗/头部”，但 Clash 一些场景确实会用这种格式——那就至少确保：

   * HTTPS
   * 服务器访问日志里避免记录 Authorization（默认不会记录 header，但会记录 URL）
3. **随机路径不是认证**：只是降低被扫到的概率。真正安全靠 Basic Auth + HTTPS（可选再加 IP allowlist）。
4. **private gist + token**：token 放在 `/etc/gist-sub.env` 且 `chmod 600`，不要写进脚本/仓库。

---

## 你可以按这个“最短落地步骤”走

1. 生成随机路径：`openssl rand -hex 16`
2. 写 `/etc/gist-sub.env`（填 gist id / token / PATH_TOKEN）
3. 放脚本到 `/opt/gist-sub/fetch_gist.py`，手动跑通一次
4. 上 systemd timer 定时更新
5. Nginx/Caddy 配好静态文件 + Basic Auth + HTTPS
6. 用最终 URL 在外部客户端订阅

---

如果你愿意再往前一步（更像产品而不是脚本），下一阶段我会建议你加两件事：

* **“健康检查”文件**（例如 `/healthz` 返回更新时间/etag），方便监控拉取是否失败
* **“变更校验”**：拉到的 YAML 先用简单规则校验（比如确保包含 `proxies:` 或 `proxy-groups:`），避免把错误页写出去导致所有客户端炸掉。
