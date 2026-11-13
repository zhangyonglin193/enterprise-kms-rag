"""跨平台受控启动器。端口冲突即退出；不换端口、不终止其他进程。"""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_values(path):
    from dotenv import dotenv_values
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"环境文件不存在：{path}")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("环境文件需仅属主可读写（chmod 600）")
    return {k: v for k, v in dotenv_values(path, interpolate=False).items() if v is not None}


# RAG 检索/生成调参键（对齐 config.py 的环境变量），KMS 启动时与 QA 对比打印
_RAG_TUNING_KEYS = (
    "CHUNK_SIZE", "CHUNK_OVERLAP", "TOP_K_RETRIEVE", "TOP_K_RERANK",
    "PARENT_EXPAND_TOPN", "MAX_CONTEXT_CHARS", "ENABLE_RERANK", "ENABLE_BM25",
    "BM25_TOP_K", "RRF_K", "ENABLE_TWO_STAGE", "ENABLE_QUERY_REWRITE",
    "ENABLE_CACHE", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_MAX_TOKENS",
)


def _print_rag_tuning_diff(qa, kms):
    """启动前打印 QA/KMS 的 RAG 调参差异：两库口径漂移须在启动时可见。"""
    diffs = [(k, qa.get(k), kms.get(k)) for k in _RAG_TUNING_KEYS
             if qa.get(k) != kms.get(k)]
    if diffs:
        print("[RAG 调参差异 QA vs KMS]")
        for k, a, b in diffs:
            print(f"  {k}: QA={a!r}  KMS={b!r}")
    else:
        print("[RAG 调参] QA 与 KMS 一致")


def deployment_values(qa_file, kms_file):
    qa, kms = load_values(qa_file), load_values(kms_file)
    if int(qa.get("QA_PORT", "6341")) != 6341:
        raise ValueError("评测端口只能为 6341")
    if not 6342 <= int(kms.get("KMS_PORT", "6342")) <= 6350:
        raise ValueError("KMS 端口只能为 6342～6350")
    # 6341 不做员工鉴权，因此绝不能复用企业数据库或向量索引。
    if not qa.get("MYSQL_DATABASE") or not kms.get("MYSQL_DATABASE") or qa["MYSQL_DATABASE"] == kms["MYSQL_DATABASE"]:
        raise ValueError("QA 与 KMS 必须使用不同数据库名称")
    defaults = {"FAISS_INDEX_PATH": "data/faiss/index", "UPLOAD_DIR": "data/uploads", "DOCS_DIR": "data/docs"}
    qa_paths = [(ROOT / qa.get(key, default)).resolve() for key, default in defaults.items()]
    kms_paths = [(ROOT / kms.get(key, default)).resolve() for key, default in defaults.items()]
    for a in qa_paths:
        for b in kms_paths:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError("QA 与 KMS 的全部数据路径必须隔离且不得相互包含")
    _print_rag_tuning_diff(qa, kms)
    return qa, kms


def apply_environment(env_file, values):
    """选定文件为项目配置唯一来源；保留 PATH 等操作系统变量。"""
    prefixes = ("MYSQL_", "QA_", "KMS_", "GW_", "FEISHU_", "WECOM_", "MODEL_", "LLM_",
                "EMBEDDING_", "RERANKER_", "OCR_", "CHUNK_", "TOP_K_", "ENABLE_", "CACHE_",
                "QUERY_REWRITE_", "THREAD_POOL_", "UVICORN_", "BM25_", "RRF_")
    exact = {"FAISS_INDEX_PATH", "UPLOAD_DIR", "DOCS_DIR", "MAX_CONTEXT_CHARS", "RAG_ENV_FILE"}
    for key in list(os.environ):
        if key.startswith(prefixes) or key in exact:
            os.environ.pop(key)
    os.environ.update(values)
    os.environ["RAG_ENV_FILE"] = str(Path(env_file).resolve())


def bind_socket(role, host, port):
    """抢占端口并返回监听 socket 列表。

    本机监听（127.0.0.1）时同时绑定 IPv6 loopback（::1）：
    Windows 上 `localhost` 同时解析到 ::1 与 127.0.0.1，若服务只听 IPv4，
    浏览器走 IPv6 时连接被拒，fetch 报 "Failed to fetch"。双栈回环绑定消除
    该间歇性故障，且仍仅限本机访问（不暴露到网卡）。

    返回的 socket 列表由调用方负责关闭（通常用 try/finally）。
    """
    if role not in ("qa", "kms"):
        raise ValueError("未知服务角色")
    if role == "qa" and port != 6341 or role == "kms" and not 6342 <= port <= 6350:
        raise ValueError("角色与端口不匹配")
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("当前启动器仅支持 IPv4 本机或全部网卡监听")
    socks = []
    # IPv4 主 socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((host, port))
        s.listen(128)
        socks.append(s)
    except BaseException:
        s.close()
        raise
    # 本机监听额外开 IPv6 loopback（::1），与 IPv4 互不冲突
    if host == "127.0.0.1":
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                s6.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::1", port))
            s6.listen(128)
            socks.append(s6)
        except OSError:
            # IPv6 不可用（无栈/被禁用）则仅用 IPv4，不阻断启动
            s6.close()
    return socks


def run(role, env_file=None, qa_file=None):
    env_file = Path(env_file or ROOT / (".env" if role == "qa" else ".env.kms")).resolve()
    values = load_values(env_file)
    if role == "kms":
        deployment_values(qa_file or ROOT / ".env", env_file)
    # 明确使用所选文件，避免父进程遗留的数据库变量串到另一服务。
    apply_environment(env_file, values)
    from config import settings
    settings.validate_ports()
    host = settings.qa_host if role == "qa" else settings.kms_host
    port = settings.qa_port if role == "qa" else settings.kms_port
    # 导入应用前抢占自己的指定 socket；绑定失败不触发应用迁移/模型调用。
    socks = bind_socket(role, host, port)
    try:
        import uvicorn
        module = importlib.import_module("app.main" if role == "qa" else "run_kms")
        # 模块导入后各 module-level logger 已创建，此时注入 request_id 关联（仅 KMS 用到网关）。
        if role == "kms":
            from gateway.logctx import install
            install()
        server = uvicorn.Server(uvicorn.Config(module.app, host=host, port=port,
                                workers=1, proxy_headers=False, access_log=False,
                                timeout_graceful_shutdown=45))
        server.run(sockets=socks)
        if not server.started:
            raise RuntimeError("应用启动未就绪")
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("qa", "kms"))
    parser.add_argument("--env")
    parser.add_argument("--qa-env")
    parser.add_argument("--check", action="store_true", help="仅验证配置和端口，不连接数据库/模型")
    args = parser.parse_args()
    try:
        if args.check:
            path = args.env or ROOT / (".env" if args.role == "qa" else ".env.kms")
            values = load_values(path)
            if args.role == "kms":
                deployment_values(args.qa_env or ROOT / ".env", path)
            apply_environment(path, values)
            from config import settings
            settings.validate_ports()
            port = settings.qa_port if args.role == "qa" else settings.kms_port
            host = settings.qa_host if args.role == "qa" else settings.kms_host
            socks = bind_socket(args.role, host, port)
            for s in socks:
                s.close()
            print(f"{args.role} 配置与端口预检通过：{host}:{port}（不代表数据库/模型已就绪）")
        else:
            run(args.role, args.env, args.qa_env)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"启动拒绝：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
