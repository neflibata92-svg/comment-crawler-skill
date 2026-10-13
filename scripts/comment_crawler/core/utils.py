"""配置读取、网络 JSON 请求和全局节流工具。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import ssl
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


class ConfigurationError(ValueError):
    pass


class NetworkError(RuntimeError):
    pass


def load_json(path: str | Path) -> tuple[dict[str, Any], Path]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigurationError(f"找不到配置文件：{config_path}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"配置不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("配置文件最外层必须是 JSON 对象")
    return payload, config_path.parent


def path_from_config(value: str, config_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else config_dir / path


def validate_browser_profile_path(value: str | Path) -> str:
    """Resolve a browser profile and keep persistent login data outside Git repositories."""
    path = Path(value).expanduser().resolve()
    if any((ancestor / ".git").exists() for ancestor in (path, *path.parents)):
        raise ValueError("浏览器档案必须放在 Git 仓库之外，避免登录会话被提交")
    return str(path)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"缺少环境变量 {name}；请不要把密钥写进 config.json")
    return value


def load_env_file(path: str | Path) -> bool:
    """读取同目录 .env，且永不覆盖已经存在的进程环境变量。"""
    env_path = Path(path)
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip().strip("\"").strip("'")
        os.environ.setdefault(key, value)
    return True


def resolve_proxy(crawl_config: dict[str, Any]) -> str:
    """从非敏感配置或指定环境变量读取 HTTP(S) 代理地址。"""
    proxy_url = str(crawl_config.get("proxy_url", "")).strip()
    env_name = str(crawl_config.get("proxy_url_env", "")).strip()
    if env_name:
        proxy_url = os.environ.get(env_name, "").strip() or proxy_url
    return proxy_url


def system_ssl_context() -> ssl.SSLContext:
    """创建使用系统证书库的 TLS 上下文。

    VPN 的 HTTPS 代理可能使用已安装到 macOS 钥匙串的企业/本地根证书。
    ``truststore`` 让 Python 使用该系统信任库，而不降低证书校验强度。
    """
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def configure_system_trust() -> bool:
    """让依赖 Python ``ssl`` 的第三方 HTTP 客户端也使用系统信任库。"""
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


def open_request(request: Request, *, timeout: int, proxy_url: str = "") -> Any:
    """经可选 HTTP(S) 代理发起已验证的请求。"""
    handlers: list[Any] = [HTTPSHandler(context=system_ssl_context())]
    if proxy_url:
        handlers.insert(0, ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return build_opener(*handlers).open(request, timeout=timeout)


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
    proxy_url: str = "",
) -> dict[str, Any] | list[Any]:
    request = Request(url, headers=headers or {}, data=data)
    try:
        response_context = open_request(request, timeout=timeout, proxy_url=proxy_url)
        with response_context as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise NetworkError(f"HTTP {exc.code}：请求被拒绝或失败") from None
    except (URLError, TimeoutError, ssl.SSLError) as exc:
        raise NetworkError(f"网络请求失败：{type(exc).__name__}") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NetworkError("接口未返回 JSON 数据") from exc


@dataclass
class RateLimiter:
    delay_seconds: float
    _last_request_at: float = field(default=0.0, init=False)

    def wait(self) -> None:
        delay = max(0.0, float(self.delay_seconds))
        remaining = delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()


@dataclass
class CollectionResult:
    source: str
    records: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    emit: Callable[[Any], Any] | None = field(default=None, repr=False)
    fetched: int = 0
    status: str = "completed_visible"

    def add(self, record: Any) -> None:
        if self.emit is not None:
            self.emit(record)
        else:
            self.records.append(record)
        self.fetched += 1

    def extend(self, records: Iterable[Any]) -> None:
        for record in records:
            self.add(record)
