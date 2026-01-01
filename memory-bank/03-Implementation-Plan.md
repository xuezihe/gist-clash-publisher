# 实现方案（Implementation Plan）

目标：以最小风险上线 MVP（Gist 拉取 → 原子写入 → 静态发布），并保留 F1/F2/F3 的扩展点。每一步只做一个可独立验证的改动。

---

## Step 1：整理模块化目录与占位模块

**目标**  
为后续功能留出清晰扩展点，保持主流程可读性。

**约束**  
不引入第三方依赖；不改变现有功能行为（仅结构预留）。

**产出物**  
- `/opt/gist-sub/` 目录结构说明（文档级）  
- `lib/validators.py`、`lib/status.py`、`lib/registry.py` 占位接口定义（文档级）

**验收/测试**  
- PRD 中明确列出 `lib/` 的占位模块与调用点示例。

**分支/提交信息**  
- 分支：`plan/step-1-structure`  
- 提交：`docs: add modular lib placeholders in prd`

**失败处理/回滚**  
- 回滚 PRD 变更即可，不影响运行逻辑。

---

## Step 2：实现 fetch_gist MVP 脚本（单租户）

**目标**  
完成单实例拉取、原子写入、ETag 增量更新的可运行脚本。

**约束**  
- 仅使用标准库  
- 通过环境变量配置  
- 写盘必须原子化  

**产出物**  
- `/opt/gist-sub/fetch_gist.py`（代码实现）  
- `/etc/gist-sub.env`（配置模板/示例）

**验收/测试**  
- 手动运行脚本可成功拉取并写入指定路径  
- ETag 未变时不会重复写盘  

**分支/提交信息**  
- 分支：`feat/step-2-fetcher`  
- 提交：`feat: add gist fetcher MVP script`

**失败处理/回滚**  
- 停用脚本与定时器（若已启用）  
- 删除新增脚本/配置文件即可恢复。

---

## Step 3：systemd service + timer 定时执行

**目标**  
让脚本按固定周期执行并可观测。

**约束**  
- 使用 systemd timer（不使用 cron）  
- 日志可通过 journalctl 查看

**产出物**  
- `/etc/systemd/system/gist-sub.service`  
- `/etc/systemd/system/gist-sub.timer`

**验收/测试**  
- `systemctl list-timers` 可看到任务  
- `journalctl -u gist-sub.service` 可看到最近一次执行结果

**分支/提交信息**  
- 分支：`feat/step-3-timer`  
- 提交：`feat: add systemd service and timer`

**失败处理/回滚**  
- `systemctl disable --now gist-sub.timer`  
- 删除 service/timer 文件并 reload systemd。

---

## Step 4：静态发布层（Caddy/Nginx）+ Basic Auth

**目标**  
对外发布固定 URL，启用 Basic Auth 与 HTTPS。

**约束**  
- 只暴露指定路径  
- 必须启用 HTTPS（Caddy 自动或 Nginx + certbot）

**产出物**  
- Caddyfile 或 Nginx 站点配置  
- `htpasswd` 或 Caddy hash-password

**验收/测试**  
- 访问错误路径返回 404  
- 认证失败返回 401  
- 正确认证返回订阅文件

**分支/提交信息**  
- 分支：`feat/step-4-static-server`  
- 提交：`feat: add static server config with basic auth`

**失败处理/回滚**  
- 回滚站点配置并 reload server  
- 移除 Basic Auth 文件即可恢复原状。

---

## Step 5：MVP 验收与上线检查

**目标**  
形成可操作的上线清单与验收步骤。

**约束**  
- 不增加功能，仅补文档与检查清单

**产出物**  
- 上线检查清单（URL、证书、权限、定时器状态）

**验收/测试**  
- 通过清单逐条自检并记录结果

**分支/提交信息**  
- 分支：`docs/step-5-checklist`  
- 提交：`docs: add MVP launch checklist`

**失败处理/回滚**  
- 回滚文档即可，不影响线上。

---

## 预留扩展步骤（与 Backlog 对齐）

> 下列步骤在 MVP 稳定后按需逐个追加。

## Step F1：内容校验 + last-good 保护

**目标**  
避免错误内容覆盖线上订阅文件。

**约束**  
- 必须在写盘前完成校验  
- 失败不替换旧文件

**产出物**  
- `lib/validators.py` 实现  
- `fetch_gist.py` 调用校验与“最后可用版本”保护

**验收/测试**  
- 输入 HTML/空内容/格式错误时，线上文件保持不变  
- 校验通过时正常更新

**分支/提交信息**  
- 分支：`feat/f1-validators`  
- 提交：`feat: add content validation and last-good guard`

**失败处理/回滚**  
- 回滚校验模块即可恢复原行为。

---

## Step F2：结构化日志 + 状态落盘

**目标**  
提升可观测性，随时定位失败原因。

**约束**  
- 日志需结构化（JSON）  
- 统一输出 `status.json`

**产出物**  
- `lib/status.py` 实现  
- `status.json` 输出定义

**验收/测试**  
- 失败/成功日志均包含关键字段  
- `status.json` 随执行更新

**分支/提交信息**  
- 分支：`feat/f2-status`  
- 提交：`feat: add status tracking and JSON logging`

**失败处理/回滚**  
- 回滚状态落盘逻辑，脚本仍可正常更新文件。

---

## Step F3：多租户注册表

**目标**  
支持多用户/多 Gist 的独立更新。

**约束**  
- registry 驱动，不引入数据库  
- 每用户失败不影响其他用户

**产出物**  
- `/etc/gist-sub.users.json`  
- `lib/registry.py` 实现  
- `fetch_gist.py` 支持按用户循环更新

**验收/测试**  
- 多 token 并行更新  
- 单用户失败不影响其他用户输出

**分支/提交信息**  
- 分支：`feat/f3-registry`  
- 提交：`feat: add multi-tenant registry support`

**失败处理/回滚**  
- 回滚 registry 逻辑，恢复单租户流程。

---

## Step F4：访问限制（Allowlist/Geo）

**目标**  
减少 URL 泄漏带来的风险。

**约束**  
- 访问策略必须在 Web 层完成

**产出物**  
- Nginx/Caddy allowlist 配置  
- （可选）Geo 限制配置

**验收/测试**  
- 白名单 IP 可访问  
- 非白名单返回 403

**分支/提交信息**  
- 分支：`feat/f4-access-control`  
- 提交：`feat: add access allowlist rules`

**失败处理/回滚**  
- 回滚 Web 配置并 reload。
