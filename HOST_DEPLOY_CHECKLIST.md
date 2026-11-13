# 主机部署执行清单（HOST_DEPLOY_CHECKLIST）

> 适用：组委会 **Ubuntu 24.04 LTS**（OpenSSH 9.6p1）通过 **Xshell + Xftp** 部署。
> 配套 `DEPLOY.md` 阅读；本清单是它的「上机照敲版」，按 部署前 / 部署中 / 部署后 / 验收 / 运维 / 回滚 六段固化。
> 假设前提：① 本机已用 `scripts/package_release.py` 产出 `dist/enterprise-rag-<时间>.tar.gz`；
> ② 已通过**安全渠道**（非代码包、非聊天、非截图）拿到 `.env` / `.env.kms`；
> ③ DBA 已建好**两套** MySQL 库与账号（QA 库、KMS 库，名不同、账号不同权）；
> ④ 已拿到获批的模型 URL/Key/模型名。

---

## 0. 本机先打包（Windows 侧，Xshell 连接前做）

```powershell
.\venv\Scripts\python.exe scripts/package_release.py --check
.\venv\Scripts\python.exe scripts/package_release.py
# 产物：dist/enterprise-rag-<时间>.tar.gz（仅代码+文档+模板；不含 .env、venv、数据、日志）
```
Xftp 把该 tar.gz 拖到服务器**新发布目录**（不覆盖在用目录）。

---

## 1. 部署前（Pre-flight）—— 先确认再动手

```bash
# (1) Python：工程支持 3.10~3.12；24.04 默认 python3=3.12，直接用即可
python3 --version                 # 期望 3.12.x
python3 -m venv --help >/dev/null && echo "venv OK"

# (2) MySQL 连通（DBA 提供的库；QA 库与 KMS 库必须是两个不同名、不同账权的库）
mysql -h "$MYSQL_HOST" -u "$MYSQL_USER" -p -e "SELECT 1"

# (3) 登出后能否常驻（最关键，决定用不用 systemd）
loginctl show-user "$USER" --property=Linger
#   若 Linger=no，请运维执行： sudo loginctl enable-linger "$USER"
#   没有 linger 又不开 systemd → 只能前台 start.sh 并保持 Xshell 连接（比赛期间别关窗口）

# (4) 端口未被占用（6341 评测 / 6342 KMS；冲突即退出，绝不自动换端口）
bash scripts/check_port.sh 6341
bash scripts/check_port.sh 6342
```

---

## 2. 部署中（Deploy）—— 上传、解压、装依赖、放配置、预检

```bash
umask 077
mkdir -p ~/unionpay-rag-release
tar -xzf /path/to/enterprise-rag-<时间>.tar.gz -C ~/unionpay-rag-release
cd ~/unionpay-rag-release
RELEASE="$PWD"                    # 记下真实绝对路径，systemd 单元要用

# 装依赖：只建 venv + pip install + pip check，不动库/不入库/不开放防火墙
PYTHON=python3 bash deploy.sh

# 放配置（从安全渠道取得），并锁权限（Linux 下权限过开放会拒绝启动）
cp /secured/delivery/.env       .env
cp /secured/delivery/.env.kms   .env.kms
chmod 600 .env .env.kms

# 预检：先绑端口再释放，不连库/模型；两条都过才继续
venv/bin/python scripts/service.py qa  --env .env --check
venv/bin/python scripts/service.py kms --env .env.kms --qa-env .env --check
```

**`.env` / `.env.kms` 必填项速查**（详见 `DEPLOY.md §3`）：

| 项 | QA `.env` | KMS `.env.kms` |
|---|---|---|
| MYSQL_DATABASE | 竞赛库（如 `rag_qa`） | 企业库（如 `enterprise_kms`），**名不同** |
| MYSQL_USER / PASSWORD | 仅访问竞赛库 | 仅访问企业库 |
| FAISS_INDEX_PATH | `data/faiss/index` | `data/kms/faiss/index`（**路径隔离**） |
| UPLOAD_DIR / DOCS_DIR | `data/uploads` / `data/docs` | `data/kms/uploads` / `data/kms/docs` |
| QA_PORT / KMS_PORT | `6341` | `6342` |
| KMS_DEMO_SEED | `0` | `0`（真实数据禁用弱密码播种） |
| GW_MODEL_EGRESS_ALLOWED | 不控竞赛模型 | 初始 `0`，批准后才改 `1` |
| KMS_EDITOR/APPROVER/ADMIN/AUDITOR_EMPLOYEES | 不配 | 配相应工号列表（四人不得重叠） |

---

## 3. 部署后（启动）—— 二选一

### 方案 A：前台先验证（推荐第一次部署用）

```bash
bash start.sh all                  # 前台拉起 QA(6341)+KMS(6342)，Ctrl+C 停
# 看到 "HTTP就绪" 后做第 4 步验收；确认没问题再切方案 B
```

### 方案 B：systemd 用户级常驻（登出后仍运行，需 linger）

工程已带 `rag.service` / `kms.service`，只把模板路径 `/opt/unionpay-rag` 换成真实路径：

```bash
mkdir -p ~/.config/systemd/user
sed "s#/opt/unionpay-rag#$RELEASE#g" rag.service  > ~/.config/systemd/user/rag.service
sed "s#/opt/unionpay-rag#$RELEASE#g" kms.service > ~/.config/systemd/user/kms.service
systemd-analyze --user verify ~/.config/systemd/user/rag.service ~/.config/systemd/user/kms.service
systemctl --user daemon-reload
systemctl --user enable --now rag.service kms.service
systemctl --user status rag.service kms.service
journalctl --user -u kms.service -f     # 看日志（日志已导向 journal）
```

> 单元已含 `Restart=on-failure` / `UMask=0077` / `NoNewPrivileges=true`；
> 停服专用 `bash stop.sh all`（只停本项目单元，不按进程名乱杀）。

---

## 4. 验收（Acceptance）—— 必须全过才算部署成功

```bash
# 健康
curl --fail --max-time 10 http://127.0.0.1:6341/readyz
curl --fail --max-time 10 http://127.0.0.1:6342/readyz

# 真实问答（评测端口）
curl --fail --max-time 120 http://127.0.0.1:6341/chat -H 'Content-Type: application/json' \
     --data '{"question":"数字人民币是什么？"}'

# 安全边界：无 Key 访问嵌入接口应返 401（这是正确行为，不是故障）
curl --max-time 10 http://127.0.0.1:6342/gw/api/v1/embed/health   # 期望 401
# KMS 的 POST /chat 应 404（无免鉴权问答旁路）
```

### 4.1 curl 评测：准确率与性能（组委会大概率就是这么打）

工程自带一键脚本 `scripts/qa_curl_eval.sh`，**只用 curl**（不依赖 wrk/ab 等评测机
未必有的工具），跑完产出 `data/qa_curl_eval_<时间戳>/` 下的打分与延迟数据：

```bash
bash scripts/qa_curl_eval.sh --limit 20          # 先冒烟：20 题
bash scripts/qa_curl_eval.sh                     # 全量：data/union100_regression.md 100 题
bash scripts/qa_curl_eval.sh --concurrency 20    # 调并发档位
bash scripts/qa_curl_eval.sh --qset data/adv100_set.md --host 127.0.0.1 --port 6341
```

脚本五步：连通性 → **语料就绪度** → 单请求时延 → 准确率批量 → 并发吞吐。

**第二步最容易踩**：`GET /health` 里 `vectors_total` 为 0 说明语料没入库，
脚本会直接中止——因为此时后面测出来的"准确率"全是假的。先入库再测：

```bash
venv/bin/python scripts/reingest_all.py --input <语料目录> --confirm-public-data
```

手工单发（脚本之外，自己随手验）：

```bash
# 时延：看 time_total
curl -sS -o /dev/null -w 'HTTP=%{http_code} 总耗时=%{time_total}s 建连=%{time_connect}s\n' \
     --max-time 120 http://127.0.0.1:6341/chat \
     -H 'Content-Type: application/json' -d '{"question":"数字人民币是什么？"}'

# 语料就绪度
curl -sS http://127.0.0.1:6341/health | python3 -m json.tool
```

接口契约（赛题规范，勿改）：`POST /chat`，入 `{"question": "..."}`，出 `{"answer": "..."}`；
兼容 JSON / form-data / `?question=` 三种传参，避免评测系统格式不定导致 422。
注意它**只返回 answer，不带引用来源**——准确率打分需对照题库参考答案人工比对。

额外人工抽查（与 `DEPLOY.md §10` 一致）：
- 维护员/审批员**不能自批**；低密级/跨部门/草稿/过期资料不出现在问答与目录中；
- Key 无效/停用、JWT 登出/改密撤销、未绑定机器人均拒绝；
- 满盘或审计不可写时不泄露答案；平台重复事件只创建一个任务。

> 注意：`readyz` 200 **≠ 业务就绪**，模型/库是否真能用一定要发真实问答验证。

---

## 5. 常用运维命令（速查）

| 目的 | 命令 |
|---|---|
| 看 KMS 日志 | `journalctl --user -u kms.service -f` |
| 看 QA 日志 | `journalctl --user -u rag.service -f` |
| 重启两服务 | `systemctl --user restart rag.service kms.service` |
| 停止（仅本项目单元） | `bash stop.sh all` |
| 查端口占用（只查不杀） | `bash scripts/check_port.sh 6341`（或 6342） |
| 配置变更后重新预检 | `venv/bin/python scripts/service.py kms --env .env.kms --qa-env .env --check` |
| 初始化员工账号 | `venv/bin/python scripts/bootstrap_employee.py --env .env.kms --qa-env .env --employee-no E1001 --name 维护员 --department 商户服务部 --level 3 --approval-ref HR-001` |

---

## 6. 回滚 / 故障

**端口被占用**：`bash scripts/check_port.sh 6341` 查所属，交运维按其正常管理方式停止，**不使用模糊进程匹配 / kill -9 盲杀**。

**数据不一致**：停止写入 → 保存现场、审计、失败报告 → 恢复同批次 MySQL/FAISS/文档备份或离线重建；**禁止用删除较大 ID 的 chunks「修复」**。

**回滚版本**：保留旧发布目录、旧 `requirements.resolved.txt`、升级前一致快照。维护窗口内停止本版本单元 → 恢复审核过的数据库/文件快照 → 切回旧发布路径 → 重新核对权限、数据 ID、JWT 密钥、审计完整性。仅退代码不能逆转已新增数据或策略变更。

**Xshell 断开后服务全停**：即 `Linger=no` 且用前台启动。解决：开启 linger 并改用方案 B（systemd）。

---

_本清单与 `DEPLOY.md` 冲突时以 `DEPLOY.md` 为准；任何「开放公网端口 / 改 6341 代码 / 混用 QA·KMS 库」均属禁止项。_
