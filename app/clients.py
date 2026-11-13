"""统一封装四个模型客户端：LLM / Embedding / Reranker / OCR。

关键性能优化：httpx Client 实例复用（连接池），避免每次请求重建 TCP。
关键容错：赛方免费模型（embedding/rerank）有 rpm/tpm 限流，429/503 自动指数退避重试。
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import List, Optional, Sequence

import httpx

from config import settings


class _BaseClient:
    """所有客户端共享的 HTTP 基础。连接池复用 + 限流重试。"""

    # 限流重试配置（赛方免费模型 rpm/tpm 有限制）
    MAX_RETRIES = 3
    RETRY_STATUS = {429, 500, 502, 503, 504}
    # 退避基数（秒）：wait = RETRY_WAIT_BASE * 2^attempt
    # OCR 大图调用重试失败代价高（限流时逐图失败→内容丢失），子类可调大。
    RETRY_WAIT_BASE = 0.5

    def __init__(self, timeout: float = 60.0, base_url: str | None = None, api_key: str | None = None):
        # base_url/api_key 未指定时走通用（组委会）；免费模型组（Embedding/Reranker/OCR）传入 free_api_*。
        self.base_url = (base_url or settings.model_api_base).rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key or settings.model_api_key}",
            "Content-Type": "application/json",
        }
        self.timeout = timeout
        # 单例复用连接池，显著降低 RTT
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                headers=self.headers,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _post(self, path: str, payload: dict) -> dict:
        """POST 请求，带 429/503 限流重试（指数退避）。

        赛方说明：免费模型（embedding/rerank/OCR）有 rpm 和 tpm 限制，
        多人同时使用时可能被限流。此处自动重试，避免评测时单题失败。
        """
        import logging
        logger = logging.getLogger("rag")

        url = f"{self.base_url}{path}"
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.client.post(url, json=payload)

                # 限流：429/502/503/504 → 指数退避重试
                if resp.status_code in self.RETRY_STATUS:
                    wait = self.RETRY_WAIT_BASE * (2 ** attempt)
                    logger.warning(
                        f"API 限流 {resp.status_code}，{wait:.1f}s 后重试 "
                        f"({attempt+1}/{self.MAX_RETRIES}) path={path}"
                    )
                    time.sleep(wait)
                    last_error = Exception(f"HTTP {resp.status_code}: 限流")
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError:
                # 非限流的 HTTP 错误，不重试直接抛出
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                # 网络错误：重试
                wait = self.RETRY_WAIT_BASE * (2 ** attempt)
                logger.warning(
                    f"网络异常 {type(e).__name__}，{wait:.1f}s 后重试 "
                    f"({attempt+1}/{self.MAX_RETRIES}) path={path}"
                )
                time.sleep(wait)
                last_error = e

        # 重试耗尽
        raise last_error or Exception(f"请求失败 path={path}")


class LLMClient(_BaseClient):
    """大语言模型 Qwen/Qwen3-32B或DeepSeek。"""

    def __init__(self):
        super().__init__()
        self.model = settings.llm_model

    def chat(
        self,
        messages: Sequence[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        enable_thinking: bool = False,
    ) -> str | dict:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "enable_thinking": enable_thinking,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": settings.llm_max_tokens if max_tokens is None else max_tokens,
        }
        data = self._post("/chat/completions", payload)
        if stream:
            return data
        return data["choices"][0]["message"]["content"]

    def chat_with_prompt(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        messages: List[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def chat_stream(
        self,
        messages: Sequence[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool = False,
    ):
        """流式调用 LLM，逐块 yield 文本片段。

        与 chat() 平行的独立路径，不改动原有非流式接口。
        使用 httpx stream + SSE 解析，兼容 OpenAI 兼容接口的 data: {...} 格式。
        异常时抛出，由上层决定降级策略。
        """
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": True,
            "enable_thinking": enable_thinking,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": settings.llm_max_tokens if max_tokens is None else max_tokens,
        }
        url = f"{self.base_url}/chat/completions"

        with self.client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                # SSE 格式：data: {...} 或 data: [DONE]
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue


class EmbeddingClient(_BaseClient):
    """向量化模型 BAAI/bge-m3，输出 1024 维。

    关键容错：
    1. 文本清洗：去除控制字符/null 字节，避免 400 Bad Request
    2. 长度截断：硬性限制单条文本字符数，避免超出模型 token 上限
    3. 单条降级：批量请求失败时，逐条重试，跳过失败项
    """

    # bge-m3 最大输入 8192 tokens，中文 1字≈1token
    # 实际 chunk = chunk_size(300) + chunk_overlap(80) = 380 字，远低于上限
    # MAX_CHARS 取 chunk 全长（含 overlap），保证尾部信息不被截断，
    # 否则向量表征不完整、检索召回率下降
    MAX_CHARS = settings.chunk_size + settings.chunk_overlap

    def __init__(self):
        super().__init__(base_url=settings.free_api_base, api_key=settings.free_api_key)
        self.model = settings.embedding_model
        # 向量结果磁盘缓存：同一「模型+清洗后文本」只调用一次 embedding 接口，
        # 重灌时未变动的 chunk 直接复用，避免反复消耗免费模型限流配额。
        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / ".emb_cache"

    def _emb_cache_key(self, text: str) -> str:
        return hashlib.sha256((self.model + "|" + text).encode("utf-8")).hexdigest()

    def _emb_cache_get(self, text: str) -> Optional[List[float]]:
        f = self._cache_dir / f"{self._emb_cache_key(text)}.json"
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) == settings.embedding_dim:
                    return data
            except Exception:
                return None
        return None

    def _emb_cache_put(self, text: str, vec: List[float]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / f"{self._emb_cache_key(text)}.json").write_text(
                json.dumps(vec, separators=(",", ":")), encoding="utf-8"
            )
        except Exception:
            pass  # 缓存失败不影响主流程

    @staticmethod
    def _clean_text(text: str) -> str:
        import re
        if not text:
            return ""
        # 去 null 和控制字符
        text = text.replace("\x00", "")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
        # 去除 Unicode 代理对、BOM、零宽字符
        text = re.sub(r"[\ufeff\u200b-\u200f\u2028-\u202f\ud800-\udfff]", "", text)
        # 合并空白
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def embed(self, texts: str | Sequence[str]) -> List[List[float]]:
        if isinstance(texts, str):
            inputs: List[str] = [texts]
        else:
            inputs = list(texts)

        # 清洗 + 截断，记录原始位置映射（空文本用零向量占位）
        zero_vec = [0.0] * settings.embedding_dim
        cleaned: List[str] = []
        positions: List[int] = []  # cleaned 中的下标 -> 原始下标
        results: List[List[float]] = [zero_vec] * len(inputs)
        for i, t in enumerate(inputs):
            ct = self._clean_text(t)[: self.MAX_CHARS]
            if ct:
                cleaned.append(ct)
                positions.append(i)

        if not cleaned:
            return results

        # 磁盘缓存优先：命中的 chunk 直接复用向量，只对未命中部分发请求
        misses: List[str] = []
        miss_pos: List[int] = []
        for pos, ct in zip(positions, cleaned):
            cached = self._emb_cache_get(ct)
            if cached is not None:
                results[pos] = cached
            else:
                misses.append(ct)
                miss_pos.append(pos)

        if not misses:
            return results

        # 批量请求（只发未命中部分）
        try:
            embs = self._embed_batch(misses)
            for pos, ct, emb in zip(miss_pos, misses, embs):
                results[pos] = emb
                self._emb_cache_put(ct, emb)
            return results
        except Exception as e:
            import logging
            logging.getLogger("rag").warning(f"批量向量化失败，降级为单条重试: {e}")
            # 单条降级
            for pos, t in zip(miss_pos, misses):
                try:
                    data = self._post("/embeddings", {"input": [t], "model": self.model})
                    emb = data["data"][0]["embedding"]
                    results[pos] = emb
                    self._emb_cache_put(t, emb)
                except Exception as e2:
                    # 打印响应体便于诊断
                    resp_text = ""
                    if hasattr(e2, "response"):
                        resp_text = e2.response.text[:300]
                    logging.getLogger("rag").warning(
                        f"单条向量化失败 [{pos}] len={len(t)}: {e2} resp={resp_text}"
                    )
                    results[pos] = zero_vec
            return results

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        payload = {"input": texts, "model": self.model}
        data = self._post("/embeddings", payload)
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    def embed_one(self, text: str) -> List[float]:
        return self.embed(text)[0]


class RerankerClient(_BaseClient):
    """重排模型 BAAI/bge-reranker-v2-m3（免费模型组，走 free_api_*）。"""

    def __init__(self):
        super().__init__(base_url=settings.free_api_base, api_key=settings.free_api_key)
        self.model = settings.reranker_model

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int | None = None,
        return_documents: bool = False,
    ) -> List[dict]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "return_documents": return_documents,
            "top_n": top_n if top_n is not None else len(documents),
        }
        data = self._post("/rerank", payload)
        return data.get("results", [])


class OCRClient(_BaseClient):
    """多模态 OCR 模型 PaddlePaddle/PaddleOCR-VL-1.5（免费模型组，走 free_api_*）。

    与 Embedding/Reranker 共用免费模型组 API（FREE_API_BASE/KEY），未配置时
    fallback 到组委会通用配置。最终部署时删除 FREE_API_* 即可全部走组委会。
    """

    def __init__(self):
        super().__init__(timeout=30.0, base_url=settings.free_api_base, api_key=settings.free_api_key)
        self.model = settings.ocr_model
        # OCR 大图调用限流时重试失败代价高（逐图失败→内容丢失），退避基数调大
        self.RETRY_WAIT_BASE = 2.0
        # OCR 结果磁盘缓存（通用复用）：同一图片字节+prompt+模型只转录一次，
        # 重灌/干跑/定点重 OCR 复用结果，避免重复烧限流配额。
        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / ".ocr_cache"

    def _cache_get(self, key: str) -> Optional[str]:
        f = self._cache_dir / f"{key}.txt"
        if f.exists():
            try:
                return f.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _cache_put(self, key: str, text: str) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / f"{key}.txt").write_text(text, encoding="utf-8")
        except Exception:
            pass  # 缓存失败不影响主流程

    def ocr(
        self,
        image_path: str | Path | None = None,
        image_base64: str | None = None,
        prompt: str = "请识别图片中的全部文字，并保持原有段落结构。",
    ) -> str:
        if image_base64 is None:
            if image_path is None:
                raise ValueError("必须提供 image_path 或 image_base64")
            image_base64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")

        # 缓存键：图片字节 + prompt + 模型。图片字节相同即同一张图，prompt/模型变化各自独立。
        cache_key = hashlib.sha256(
            (image_base64 + "|" + prompt + "|" + self.model).encode("utf-8")
        ).hexdigest()[:16]
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        mime = "image/png"
        if image_path is not None:
            ext = Path(image_path).suffix.lower()
            mime = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".webp": "image/webp",
            }.get(ext, "image/png")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "stream": False,
            # 转录任务必须确定性采样：temperature=0 抑制 VLM 对难图的采样型编造（跨语种幻觉等），
            # max_tokens 防重复坍缩输出无限膨胀（doc104 重复爆炸的诱因之一）
            "temperature": 0,
            "max_tokens": 2048,
        }
        data = self._post("/chat/completions", payload)
        text = data["choices"][0]["message"]["content"]
        self._cache_put(cache_key, text)
        return text
