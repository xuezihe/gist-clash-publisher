# Future List / Backlog

> 目标：核心功能（拉取 Gist → 生成静态订阅文件 → Nginx/Caddy Basic Auth 暴露）稳定后，再逐步增强安全性、可观测性与多租户能力。

---

## F1 订阅内容校验 + 最后可用版本保护（Prevent Bad Publish）

**要解决的问题**：拉取到错误内容（HTML 错误页/限流页、空文件、格式损坏）被写到线上，导致所有客户端订阅崩掉。

**实现要点（建议由简到强）**

1. **快速拒绝**：检测内容像 HTML（`<html` / `<!doctype`）、空内容、异常 Content-Type。
2. **YAML 可解析**：`safe_load` 成功。
3. **最小结构校验**：至少包含 provider 关键字段（如 `proxies` 或 `proxy-groups`，按你的订阅格式定）。
4. **last-good 保护**：仅当校验通过才原子替换线上文件；失败时保持旧文件不动，并记录错误原因。

**验收标准**

* 拉取失败或内容不合格时：线上订阅文件不变；日志可看到失败原因。
* 拉取成功且内容合格时：线上订阅文件更新；记录更新时间/etag/sha。

---

## F2 可观测性：结构化日志 + 状态落盘（Observe & Alert）

**要解决的问题**：你需要快速回答：是否在更新？上次成功是什么时候？失败原因是什么？

**实现要点**

* **JSON 结构化日志**：`event / user_token / gist_id / etag / bytes / duration_ms / status / error`。
* **状态文件**：输出 `status.json`（包含 `last_attempt_ts / last_success_ts / last_error / etag / sha256`）。
* （可选）**静态 health 文件**：例如 `healthz.txt` 写“最后成功时间/失败原因”。

**验收标准**

* `journalctl` 一眼能看出 success/fail 与原因。
* 任意时刻读取 `status.json` 就能定位最近一次成功更新时间。

---

## F3 多租户发布（方案A）：多用户/多文件/到期降级订阅（Multi-tenant via Per-User Output）

**要解决的问题**：同一台机器托管多个订阅；不同用户拿到不同内容；用户到期后自动“失效”。

### F3a 多订阅实例（多用户/多文件）

**实现要点**

* 引入 **User Registry**（例如 `users.json` / `users.yaml`）：

  * `user_token`（路径 token）
  * `gist_id` / `gist_file`
  * `output_name`（如 `proxies.yaml`）
  * `enabled` / `note`
* 输出路径形态：`/var/www/sub/<user_token>/<output_name>`

**验收标准**

* 同时发布 N 个 token 的订阅文件，每个 token 独立更新与独立失败不互相影响。

### F3b 到期降级订阅（Graceful Expiration via Placeholder Provider）

**你当前设想（推荐）**：用户到期后仍允许拉取订阅，但返回一个**结构合法、内容不可用**的占位 `proxies.yaml`，让客户端下次更新后节点自动清空/不可用。

**实现要点**

* registry 增加 `expires_at`。
* 更新逻辑：

  * 未到期：写真实 gist 内容（经过 F1 校验）
  * 已到期：写 `expired_proxies.yaml` 模板（同样要保证 YAML 合法）
* 占位模板建议保留两种策略：

  * **空列表**：`proxies: []`
  * **不可用假节点**：`EXPIRED - Renew required`（更兼容一些客户端 UI）

**验收标准**

* 到期用户下次拉取后：客户端节点变空或全部不可用。
* 未到期用户不受影响。
* 线上始终返回合法 YAML（不会输出 HTML 错误页）。

---

## F4 访问限制：CIDR 白名单与地理限制（Restrict Access）

**要解决的问题**：即使订阅 URL 泄漏，也尽量限制可拉取范围。

### F4a CIDR Allowlist（优先做）

**实现要点**

* 配置 `ALLOW_CIDRS=1.2.3.0/24,5.6.7.8/32,...`
* 在 Nginx/Caddy 对订阅路径应用 allow/deny。

**验收标准**

* 非白名单 IP 返回 403；白名单正常拉取。

### F4b Geo Restriction（可选）

**实现要点**

* Nginx + GeoIP2（需要数据库/模块），或 Cloudflare 前置（使用国家代码 header）。

**验收标准**

* 指定国家/地区允许，其它拒绝，且真实 IP 获取准确。

---

## 备注：不纳入当前阶段的非目标（Non-goals for MVP）

* 不做动态鉴权服务层（FastAPI/Node gateway）。
* 不做复杂的订阅转换/多客户端格式变换。
* 不做数据库（SQLite/Postgres）依赖；优先用 registry 文件落盘。
