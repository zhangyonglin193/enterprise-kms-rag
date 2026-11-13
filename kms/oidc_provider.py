"""统一登录提供方适配器 —— 内置模拟 IdP / 外部 OI 平台（OIDC / OAuth2）。

参照 IBM 等企业 KMS：知识问答系统作为 Relying Party 接入企业统一身份平台
（OI 平台 / AD 联合身份）。本模块把「校验外部 id_token 并映射出内部工号」抽象为
标准 OIDCProvider 接口：

- BuiltinOIDCProvider   内置模拟 IdP（本地/竞赛演示，令牌交换走 /sso/token）
- ExternalOIDCProvider  外部 IdP：JWKS 验签（惰性依赖 PyJWT + cryptography）

通过 KMS_OIDC_PROVIDER（builtin|external）选择实现，业务代码不感知具体 IdP。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import HTTPException

from app.logger import get_logger
from config import settings

logger = get_logger("kms.oidc_provider")


class OIDCProvider(ABC):
    """统一登录提供方标准接口。"""

    name: str = "builtin"

    @abstractmethod
    def verify_id_token(self, id_token: str) -> dict:
        """校验 id_token 并返回标准化 claims。

        Returns:
            {employee_no, name, department, level, iss, aud, sub}
        校验失败抛 HTTPException(401)；IdP 不可达抛 HTTPException(503)。
        """


class BuiltinOIDCProvider(OIDCProvider):
    """内置模拟 IdP：不对外部 id_token 验签，仅用于本地/竞赛演示。

    外部令牌交换入口 /sso/exchange 在本模式下拒绝，引导使用内置 /sso/token。
    """

    name = "builtin"

    def verify_id_token(self, id_token: str) -> dict:
        raise HTTPException(400, "内置模拟 IdP 不校验外部 id_token，请使用 /kms/api/auth/sso/token 交换")


class ExternalOIDCProvider(OIDCProvider):
    """外部 OI 平台 IdP：基于 JWKS 的 RS256 验签。

    安全校验：签名（JWKS 公钥）+ issuer + audience + exp。工号 claim 由
    KMS_OIDC_EMPLOYEE_CLAIM 指定（缺省 emp）。
    """

    name = "external"

    def verify_id_token(self, id_token: str) -> dict:
        try:
            import jwt
        except Exception as exc:  # pragma: no cover - 依赖缺失分支
            raise RuntimeError("外部 OIDC 验签需要 PyJWT 与 cryptography，请 pip install pyjwt cryptography") from exc

        if not id_token:
            raise HTTPException(401, "缺少 id_token")

        try:
            signing_key = jwt.PyJWKClient(settings.kms_oidc_jwks_url).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.kms_oidc_client_id,
                issuer=settings.kms_oidc_issuer,
            )
        except HTTPException:
            raise
        except Exception as e:
            kind = type(e).__name__
            logger.warning(f"外部 id_token 校验失败: {kind}: {e}")
            if "Connection" in kind or "URL" in kind or "Timeout" in kind:
                raise HTTPException(503, "外部身份提供商暂不可用") from None
            raise HTTPException(401, "外部令牌校验失败") from None

        employee_no = (
            claims.get(settings.kms_oidc_employee_claim)
            or claims.get("employee_no")
            or claims.get("emp")
        )
        if not employee_no:
            raise HTTPException(401, "id_token 缺少工号 claim")

        try:
            level = int(claims.get("level", 0) or 0)
        except (TypeError, ValueError):
            level = 0

        return {
            "employee_no": str(employee_no).strip(),
            "name": str(claims.get("name", "") or ""),
            "department": str(claims.get("department", "") or ""),
            "level": max(0, min(3, level)),
            "iss": claims.get("iss"),
            "aud": claims.get("aud"),
            "sub": claims.get("sub"),
        }


def build_oidc_provider() -> OIDCProvider:
    """依 KMS_OIDC_PROVIDER 构造登录提供方适配器。"""
    provider = (settings.kms_oidc_provider or "builtin").strip().lower()
    if provider == "builtin":
        return BuiltinOIDCProvider()
    if provider == "external":
        return ExternalOIDCProvider()
    raise ValueError(f"未知 OIDC 提供方: {provider}（仅支持 builtin/external）")
