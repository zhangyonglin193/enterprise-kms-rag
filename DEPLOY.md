# Windows 本地与 Xshell/Linux 部署手册

版本：2.0，2026-10-15。代码已提供跨平台启动与非破坏安装；真实 Linux、MySQL、模型和办公平台仍需按本文验收。不能仅凭进程启动或离线测试宣称生产就绪。

## 1. 不可突破的端口与数据规则

| 服务 | 监听 | 用途 |
|---|---|---|
| QA | `0.0.0.0:6341`（可改为本机监听，端口不可改） | 组委会 `POST /chat` 测评；唯一对外暴露的主业务入口 |
| KMS + 企业网关 | `127.0.0.1:6342` | 员工门户、治理、飞书/企微回调、嵌入 API；可配置6342～6350 |
| 嵌入 BFF 示例 | `127.0.0.1:6343` | 可选；不得与实际KMS端口相同 |
| 其余6344～6350 | 默认不监听 | 经批准后再规划 |

- 不新建或抢占80/443/8000/8080等监听入口。已有MySQL、SSH和模型服务是外部依赖，本项目不部署这些基础设施。
- KMS与QA必须使用不同数据库名称、不同且不互相包含的FAISS/上传/文档目录；脚本交叉检查全部三类路径。生产数据库账号还应分别授权，不能仅分库而共用全库特权账号。
- 6341不做员工认证，因此只能装载经批准的竞赛公开资料。真实企业资料不准为了省事复制到评测库。
- 端口冲突即退出；不改端口、不终止占用者。只使用本文启动器，不使用任意uvicorn命令绕过约束。脚本不能阻止拥有OS权限的人另开程序。
- KMS默认只在本机可达。SSH隧道用于员工浏览器，不等于飞书/企微服务器能回调。若组委会没有批准的HTTPS接入设施，先完成本机功能，平台联调记为阻塞，不能擅自开公网端口。

## 2. 前置条件

1. 建议Python3.11；安装脚本接受3.10～3.12。Windows使用独立venv，不能把Windows虚拟环境复制到Linux。
2. 推荐MySQL8.0、InnoDB、utf8mb4。由DBA提前提供两套数据库/账号。首次启动含CREATE/ALTER增量迁移，必须在批准维护窗口、备份后执行；没有DROP数据库或自动删表操作。
3. 已批准的模型URL、Key、模型名与Embedding维度。企业默认`GW_MODEL_EGRESS_ALLOWED=0`；不要沿用竞赛HTTP模型地址处理金融资料。
4. 目标磁盘、内存、网络、文件ACL、时间同步由运维确认。SQLite不能部署在NFS，多worker尚不支持。线程数和并发上限必须经压测确定。
5. 真实配置、账号密码、平台Secret不得通过聊天、截图、日志、命令行参数或代码包传输。

## 3. Windows 本地配置与验证

以下在项目根目录PowerShell执行。无需运行Activate.ps1或修改系统执行策略。

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

已有venv时跳过创建。依赖安装可能改变现有环境，升级应使用新发布目录，保留旧版本。requirements使用兼容范围而非全平台锁文件；不要把pip check说成供应链安全审计。

配置文件：不存在时才从`.env.example`复制为`.env`，从`.env.kms.example`复制为`.env.kms`，再用本地编辑器填写。不要覆盖已有真实配置。模板可提交，实际文件不可提交。

| 配置项 | QA `.env` | KMS `.env.kms` |
|---|---|---|
| MYSQL_DATABASE | 竞赛专用库 | 独立企业库，例如enterprise_kms |
| MYSQL_USER/PASSWORD | 仅访问竞赛库 | 仅访问企业库 |
| FAISS_INDEX_PATH | data/faiss/index | data/kms/faiss/index |
| UPLOAD_DIR | data/uploads | data/kms/uploads |
| DOCS_DIR | data/docs | data/kms/docs |
| GW_STATE_PATH | 不用于企业服务 | data/kms/gateway/state.sqlite3 |
| GW_AUDIT_DIR | 不用于企业服务 | data/kms/audit |
| QA_PORT / KMS_PORT | 6341 / 6342 | 6341 / 6342 |
| KMS_DEMO_SEED | 0 | 0 |
| GW_MODEL_EGRESS_ALLOWED | 不控制竞赛模型调用 | 初始0，批准后才改1 |
| UVICORN_WORKERS | 1 | 1，启动器强制单进程 |

启动器先清理父进程的项目配置变量，再加载选定文件，避免QA/KMS串配置。业务路径相对于项目根目录，非终端当前目录。配置文件值按字面读取，不展开`${...}`。签名密钥可在KMS环境文件中配置独立随机值（至少32字符）；为空时自动生成到企业数据目录，持久化失败拒绝服务。

先做只读配置/绑定预检，再启动：

```powershell
.\venv\Scripts\python.exe scripts/service.py qa --env .env --check
.\venv\Scripts\python.exe scripts/service.py kms --env .env.kms --qa-env .env --check
.\start_local.bat all
```

也可`.\start_local.bat qa`或`kms`。all模式需要两套配置与数据库均可用。预检暂时绑定指定端口后释放，不连接MySQL/模型；实际启动再次绑定，避免“预检后别人占用”造成自动换端口。配置导入可能创建空数据目录。

看到“HTTP就绪”后再做问答检查。窗口必须保持运行，Ctrl+C停止该次启动的子进程；不会按进程名称终止其他服务。浏览器访问`http://127.0.0.1:6342/`。

## 4. 初始员工与职责

KMS可在空用户表下启动，但不能登录。不要启用弱密码演示播种来处理真实数据。

由人事、安全、业务负责人复核员工清单和密级后，操作员在服务器控制台运行：

```powershell
.\venv\Scripts\python.exe scripts/bootstrap_employee.py --env .env.kms --qa-env .env --employee-no E1001 --name 测试维护员 --department 商户服务部 --level 3 --approval-ref HR-TEST-001
```

工具交互输入密码，不回显、不放入命令行；记录OS操作员、工号及线下审批编号，已存在员工拒绝覆盖。此编号不代表系统已验证电子签名或审批真实性；需甲方线下流程和控制台权限保证。账号密码安全交付后要求员工修改，系统尚未强制首次改密。

本系统无「管理员」也无「编辑员」白名单：身份只有「员工」与「运营审计」两类。
所有在职员工均可申请删除/导入/改变密级，把关靠双人审批而非身份授权；审批人由
「同部门或不限 + 安全职级 ≥ 文档密级 + HR 涉密准入 + 排除申请人本人」派生，
不按名单配置。`.env.kms` 只需配运营审计员工号：

```dotenv
KMS_AUDITOR_EMPLOYEES=E1004
```

这些只是示例工号，不是预置账号。维护与审批应同部门并有足够内容密级，名单不能重叠；管理员/审计员也不得重叠。HTTP端不开放任意员工密级上报。真实HR同步、离职自动停用、SSO/MFA、忘记密码恢复要在生产上线前对接。

## 5. 数据准备与迁移

### 5.1 迁移已有竞赛数据（优先）

1. 停止源服务写入，记录模型名、Embedding维度、分块策略、源发布版本。
2. 在同一维护窗口备份MySQL和FAISS索引、必要文档；建立文件校验清单，记录备份时间。
3. 由DBA恢复到目标竞赛库；经批准传输相应`data/faiss/index.index`与公开文档目录。
4. 更新目标配置和路径。Windows绝对source_path不能在Linux直接当作有效文件地址，必要时依据映射清单迁移，禁止不受控全文路径替换。
5. 启动后校验FAISS与chunks的实际ID集合、重复ID、孤立分块；不同即拒绝，不执行自动删数据。

数量一致也不代表向量语义一致，不能把不同Embedding模型的索引混用。数据库和索引必须是同一快照。

### 5.2 从公开文件重新入库（可能产生模型费用）

在QA服务已停止、数据已审批、具备可用模型凭据后手动执行：

```bash
venv/bin/python scripts/ingest_batch.py --env .env --input RAG_repository --confirm-public-data
```

Windows使用`.\venv\Scripts\python.exe`执行同样参数。部署脚本不会自动执行此操作。该脚本不用于企业发布；有失败时非零退出，报告位于docs目录父级的ingest_report.json。无数据文件则拒绝。旧.doc和扫描图片处理可能依赖额外解析/模型能力，不承诺所有竞赛格式在新主机无需准备就能解析。

### 5.3 企业库

推荐空库起步：L3维护员通过工作台上传已预审文件 → 查看草稿 → 提交策略 → 独立审批员查看原文并批准 → 授权员工问答。入库本身会调用模型，必须先完成模型出域批准。

旧企业数据迁移后`publication_approved`默认0，不自动公开。缺归属的数据不允许任意部门抢领；由资产负责人提供逐文档归属/分类清单，DBA在维护窗口备份后补正并保持draft、审批标记0，再走双人发布。禁止批量直接设published或默认L0。完整历史版本、旧工单不在本次可用入口中。

## 6. 代码打包与 Xshell/Xftp 上传

```powershell
.\venv\Scripts\python.exe scripts/package_release.py --check
.\venv\Scripts\python.exe scripts/package_release.py
```

输出`dist/enterprise-rag-<时间>.tar.gz`。使用白名单打包代码、当前文档及模板；不含.env/.env.kms、数据、原始知识文档、venv、日志和审计。代码白名单不是Secret扫描：发布前仍应审查代码是否误写凭据。

用Xftp上传代码包到新发布目录，不覆盖在用目录。使用Xshell登录后，按甲方批准路径操作，以下`$HOME/unionpay-rag-release`仅为示例：

```bash
umask 077
mkdir -p "$HOME/unionpay-rag-release"
tar -xzf /approved/upload/enterprise-rag-<时间>.tar.gz -C "$HOME/unionpay-rag-release"
cd "$HOME/unionpay-rag-release"
PYTHON=python3.11 bash deploy.sh
```

先用实际文件名替换尖括号占位。`deploy.sh`仅创建缺失venv、安装requirements、pip check、输出requirements.resolved.txt；不复制环境、不入库、不启动、不开放防火墙。`deploy_full.sh`只是兼容入口，旧重置部署逻辑已停用。

通过安全配置渠道分别提供.env/.env.kms，编辑真实值后：

```bash
chmod 600 .env .env.kms
venv/bin/python scripts/service.py qa --env .env --check
venv/bin/python scripts/service.py kms --env .env.kms --qa-env .env --check
venv/bin/python -m unittest discover -s tests -v
bash start.sh all
```

Linux预检会拒绝对组/其他用户开放的配置文件。原始文件、索引、审计、SQLite及其父目录也应使用受限权限和加密备份。不要对整个data目录设置全员可读。

## 7. Linux 服务化

仓库`rag.service`和`kms.service`为用户级systemd模板。替换其中所有`/opt/unionpay-rag`为实际发布目录；不要使用旧文档中的示例账号。确认未覆盖用户已有同名单位，再安装到`~/.config/systemd/user/`。

```bash
systemd-analyze --user verify ~/.config/systemd/user/rag.service ~/.config/systemd/user/kms.service
systemctl --user daemon-reload
systemctl --user start rag.service kms.service
systemctl --user status rag.service kms.service
journalctl --user -u rag.service -u kms.service -f
```

`Type=simple`的active不代表业务ready，仍要HTTP验收。systemd会管理它自己的服务cgroup并按超时策略终止，可能在超时后强制停止自己的进程；这与脚本按名称杀其他服务不同。不要同时使用前台start.sh和systemd启动同一服务。

若需登出后持续运行，用户级systemd会话/linger由服务器运维批准配置；不要假定Xshell断开后前台服务仍运行。无用户级systemd时使用甲方批准的进程管理平台。

`bash stop.sh all`只停止明确的用户级rag.service/kms.service；它不会停止前台start.sh创建的服务，后者在原窗口Ctrl+C。

## 8. curl 验收与隧道

Linux示例：

```bash
curl --fail --max-time 10 http://127.0.0.1:6341/readyz
curl --fail --max-time 10 http://127.0.0.1:6342/readyz
curl --fail --max-time 120 http://127.0.0.1:6341/chat -H 'Content-Type: application/json' --data '{"question":"数字人民币是什么？"}'
curl --max-time 10 http://127.0.0.1:6342/gw/api/v1/embed/health
```

最后一条未带Key应返回401，这是正确行为。6342的`POST /chat`应404。Windows使用curl.exe以免调用PowerShell别名，中文JSON可在API工具中发送，避免旧PowerShell引号/编码差异。

本地浏览器访问远程KMS可在Xshell设置本地转发：本地`127.0.0.1:6342` → 远程`127.0.0.1:6342`。本地KMS已占用6342时应先停止自己服务，或显式选用空闲的6344～6350作为隧道本地端口。不要让工具自动换到任意端口。

命令行等价示例（需实际获批SSH主机与用户）：

```bash
ssh -N -L 127.0.0.1:6342:127.0.0.1:6342 <用户>@<服务器>
```

平台机器人不能通过你的本地SSH浏览器隧道到达服务器。配置其回调之前，必须取得平台可达的获批HTTPS地址；不在本项目服务器新占用443。若平台不接受获批的6342～6350 HTTPS入口，则由甲方已有接入平台转发，未批准前停止平台联调。

## 9. 嵌入 BFF 运行

应用管理员创建应用，Key通过保密渠道交给宿主服务端。以PowerShell为例，在独立终端会话注入变量，不要把真实Key写进示例脚本：

```powershell
$env:EMBED_API_KEY = '<由安全渠道注入的应用Key>'
$env:KMS_BASE_URL = 'http://127.0.0.1:6342'
$env:EMBED_PORT = '6343'
.\venv\Scripts\python.exe examples/embed_bff.py
```

Linux通过受限服务环境文件注入同名变量，然后`venv/bin/python examples/embed_bff.py`。浏览器访问6343，演示页面可粘贴短期员工JWT；真实宿主应提供SSO会话，不长期保存或打印JWT。BFF审计默认data/bff/audit，可以通过BFF_AUDIT_DIR指定安全目录。Key永不返回页面。

## 10. 验收、故障处理与回滚

验收至少包括：
- 两个readyz均就绪，6341已知评测问题返回answer，6342无免鉴权QA旁路。
- 维护员/审批员不能自批，低密级/跨部门/草稿/过期资料不出现在问答和目录中。
- Key无效/停用、JWT登出/改密撤销、未绑定机器人均拒绝。
- 满盘或审计不可写时不泄露答案，平台重复事件只创建一个任务。
- 停止/重启后撤销记录和回调任务保留；验证失败队列、平台重复投递与人工处置。
- 真实MySQL事务并发、失败恢复、Linux中文文件路径、WindowsCtrl+C行为及浏览器交互验收。
- 飞书/企微真实加密回调、URL验证、私聊推送、平台可信IP及超时达标。

端口被占用：`bash scripts/check_port.sh 6341`或6342，仅查看，不终止进程。向运维核实所属服务后通过其正常管理方式停止，不使用模糊进程匹配。

数据不一致：停止写入，保存现场、审计和失败报告；恢复同批次MySQL/FAISS/文档备份或离线重建。禁止用删除较大ID的chunks“修复”。上传失败可能留下孤立文件或分块，必须核对后处置。

回滚：保留旧发布目录、旧依赖清单和升级前一致快照。在维护窗口停止本版本自己的单位，恢复审核过的数据库/文件快照后切回旧发布路径。仅退代码不能逆转已新增数据或策略变更。恢复后重新核对权限、数据ID、JWT密钥及审计完整性。

当前未形成WORM、集中告警、备份恢复演练、全链路压测和监管测评闭环。只有完成`docs/enterprise_delivery.md`中的生产准入清单，才能由甲方决定商用上线。
