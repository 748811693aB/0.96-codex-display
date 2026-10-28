#!/usr/bin/env python3
"""Read the remaining DeepSeek balance without third-party packages.

Two credential kinds are supported:

* a Platform API key (``sk-...``) queried through the public
  ``/user/balance`` endpoint;
* the local DeepSeek Harness account grant stored in
  ``~/.dsh/.credentials.yaml``, queried through the Platform wallet
  summary endpoint the desktop app itself uses.

Secrets are never logged. Network failures raise ``DeepSeekError`` so the
caller can keep showing the previous balance.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_PLATFORM_BASE = "https://platform.deepseek.com"
DEFAULT_DSH_HOME = "~/.dsh"
DEFAULT_DSH_CREDENTIALS = "~/.dsh/.credentials.yaml"
DEFAULT_KEY_FILES = (
    "~/.config/deepseek-display/api_key",
    "~/.config/deepseek/api_key",
    "~/.deepseek/api_key",
)
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "dsh-msu2-display/1.0"


class DeepSeekError(RuntimeError):
    """A balance lookup failed."""


class DeepSeekAuthError(DeepSeekError):
    """The stored credential was rejected; the user must sign in again."""


@dataclass(frozen=True)
class DeepSeekCredential:
    """One discovered credential. ``secret`` must never be logged."""

    kind: str  # "api_key" or "dsh_token"
    secret: str
    source: str
    base_url: str = DEFAULT_API_BASE
    extra_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DeepSeekBalance:
    """Remaining DeepSeek balance in one currency."""

    currency: str
    total: Decimal
    topped_up: Decimal | None
    granted: Decimal | None
    is_available: bool | None
    fetched_at: float
    source: str


@dataclass(frozen=True)
class DeepSeekPrice:
    """Current official API output-token price and its peak/off-peak context."""

    model: str
    metric: str
    price_per_million: Decimal
    average_per_million: Decimal
    multiple_of_average: Decimal
    is_peak: bool
    fetched_at: float


# Official prices in USD per one million output tokens. The pricing page
# defines the peak rate as exactly twice the off-peak rate.
# Source: https://api-docs.deepseek.com/quick_start/pricing/
_API_OUTPUT_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "deepseek-v4-pro": (Decimal("1.98"), Decimal("3.96")),
    "deepseek-flash": (Decimal("0.60"), Decimal("1.20")),
}


def _normalise_price_model(model: str) -> str:
    key = model.strip().lower()
    aliases = {
        "pro": "deepseek-v4-pro",
        "deepseek-pro": "deepseek-v4-pro",
        "flash": "deepseek-flash",
        "deepseek-v4-flash": "deepseek-flash",
    }
    return aliases.get(key, key)


def _is_peak_price_time(now: dt.datetime) -> bool:
    """Return whether *now* is in DeepSeek's weekday peak schedule (UTC)."""
    utc = now.astimezone(dt.timezone.utc) if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    return utc.weekday() < 5 and (1 <= utc.hour < 4 or 6 <= utc.hour < 10)


def current_api_price(
    model: str = "deepseek-flash",
    *,
    now: dt.datetime | None = None,
) -> DeepSeekPrice:
    """Return the current official output-token price and average multiple.

    DeepSeek publishes peak windows as 01:00–04:00 and 06:00–10:00 UTC on
    weekdays, with all other times off-peak. The service also excludes Chinese
    public holidays; this lightweight display calculation models the fixed
    weekday windows and avoids embedding a calendar that will go stale.
    """
    model_key = _normalise_price_model(model)
    try:
        off_peak, peak = _API_OUTPUT_PRICES[model_key]
    except KeyError as exc:
        raise DeepSeekError(f"Unknown DeepSeek API price model: {model}") from exc
    is_peak = _is_peak_price_time(now or dt.datetime.now(dt.timezone.utc))
    average = (off_peak + peak) / Decimal("2")
    current = peak if is_peak else off_peak
    return DeepSeekPrice(
        model=model_key,
        metric="output",
        price_per_million=current,
        average_per_million=average,
        multiple_of_average=current / average,
        is_peak=is_peak,
        fetched_at=time.time(),
    )


def format_price_multiple(value: Decimal) -> str:
    return f"{value:.2f}x"


def summarize_price(price: DeepSeekPrice) -> str:
    mode = "PEAK" if price.is_peak else "VALLEY"
    return (
        f"DeepSeek API {price.model} output: ${price.price_per_million:.2f}/1M "
        f"({mode}, {format_price_multiple(price.multiple_of_average)} average)"
    )


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_api_key_file(path: str | Path) -> str | None:
    """Return the first non-empty, non-comment line of a key file."""
    text = _read_file(Path(path).expanduser())
    if text is None:
        return None
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.lower().startswith("deepseek_api_key"):
            _, _, value = value.partition("=")
            value = value.strip().strip("'\"")
        return value or None
    return None


def read_dsh_grant(path: str | Path = DEFAULT_DSH_CREDENTIALS) -> tuple[str, str] | None:
    """Extract the platform account token and issuer from the DSH credentials file.

    The file is a tiny, flat YAML document; a targeted scan avoids depending
    on PyYAML, which this project intentionally does not require.
    """
    text = _read_file(Path(path).expanduser())
    if text is None:
        return None

    token: str | None = None
    issuer = DEFAULT_PLATFORM_BASE
    in_record = False
    record_indent = 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        is_record = stripped.startswith("deepseek-account-platform/default:")
        if is_record:
            in_record = True
            record_indent = indent
            continue
        if not in_record:
            continue
        if indent <= record_indent and not stripped.startswith(("kind:", "payload:")):
            break
        if stripped.startswith("token:"):
            token = stripped.partition(":")[2].strip().strip("'\"") or None
        elif stripped.startswith("issuer:"):
            issuer = stripped.partition(":")[2].strip().strip("'\"") or issuer
    if not token:
        return None
    return token, issuer.rstrip("/")


def _dsh_credentials_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("DSH_HOME") or DEFAULT_DSH_HOME
    return Path(home).expanduser() / ".credentials.yaml"


def discover_credential(
    explicit_key: str | None = None,
    explicit_key_file: str | None = None,
    dsh_credentials: str | None = None,
    project_dir: str | Path | None = None,
) -> DeepSeekCredential | None:
    """Find the best available DeepSeek credential.

    Priority: CLI key, ``DEEPSEEK_API_KEY``, explicit key file, well-known key
    files, project key file, then the DeepSeek Harness account grant.
    """
    if explicit_key:
        return DeepSeekCredential("api_key", explicit_key.strip(), "--deepseek-key")

    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return DeepSeekCredential("api_key", env_key, "DEEPSEEK_API_KEY")

    if explicit_key_file:
        value = read_api_key_file(explicit_key_file)
        if value:
            return DeepSeekCredential("api_key", value, str(Path(explicit_key_file).expanduser()))

    candidates: list[Path] = [Path(p).expanduser() for p in DEFAULT_KEY_FILES]
    if project_dir is not None:
        candidates.append(Path(project_dir) / ".deepseek_api_key")
        candidates.append(Path(project_dir) / "deepseek_api_key.txt")
    for candidate in candidates:
        value = read_api_key_file(candidate)
        if value:
            return DeepSeekCredential("api_key", value, str(candidate))

    grant = read_dsh_grant(_dsh_credentials_path(dsh_credentials))
    if grant is not None:
        token, issuer = grant
        return DeepSeekCredential(
            "dsh_token",
            token,
            str(_dsh_credentials_path(dsh_credentials)),
            base_url=issuer,
            extra_headers=_platform_headers(),
        )
    return None


def _platform_headers() -> tuple[tuple[str, str], ...]:
    locale = os.environ.get("LANG", "")
    wire_locale = "zh_CN" if locale.lower().startswith("zh") else "en_US"
    return (
        ("x-client-bundle-id", ""),
        ("x-client-platform", "desktop-mac" if sys.platform == "darwin" else "web"),
        ("x-client-version", "0.1.0"),
        ("x-client-locale", wire_locale),
        ("x-client-timezone-offset", str(time.timezone)),
    )


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise DeepSeekError(f"Unexpected balance value: {value!r}") from exc


def _wallet_totals(wallets: object) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    if not isinstance(wallets, list):
        return totals
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        currency = str(wallet.get("currency") or "").upper()
        if not currency:
            continue
        totals[currency] = totals.get(currency, Decimal(0)) + _decimal(wallet.get("balance", "0"))
    return totals


def _preferred_currency(totals: Mapping[str, Decimal]) -> str:
    if "CNY" in totals:
        return "CNY"
    if "USD" in totals:
        return "USD"
    return next(iter(totals))


def parse_api_balance(payload: object, *, fetched_at: float | None = None) -> DeepSeekBalance:
    """Parse ``GET https://api.deepseek.com/user/balance``."""
    if not isinstance(payload, dict):
        raise DeepSeekError("Unexpected balance response")
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise DeepSeekError("Balance response carried no balance_infos")
    wanted = next((i for i in infos if isinstance(i, dict) and i.get("currency") == "CNY"), None)
    if wanted is None:
        wanted = next((i for i in infos if isinstance(i, dict)), None)
    if wanted is None:
        raise DeepSeekError("Balance response carried no usable wallet")
    total = _decimal(wanted.get("total_balance", "0"))
    topped = wanted.get("topped_up_balance")
    granted = wanted.get("granted_balance")
    return DeepSeekBalance(
        currency=str(wanted.get("currency") or "CNY").upper(),
        total=total,
        topped_up=_decimal(topped) if topped is not None else None,
        granted=_decimal(granted) if granted is not None else None,
        is_available=payload.get("is_available") if isinstance(payload.get("is_available"), bool) else None,
        fetched_at=time.time() if fetched_at is None else fetched_at,
        source="api",
    )


def parse_platform_balance(payload: object, *, fetched_at: float | None = None) -> DeepSeekBalance:
    """Parse the Platform ``get_user_summary`` wallet payload."""
    if not isinstance(payload, dict):
        raise DeepSeekError("Unexpected platform response")
    if payload.get("code") != 0:
        raise DeepSeekError(f"Platform error code {payload.get('code')!r}")
    data = payload.get("data") or {}
    if not isinstance(data, dict) or data.get("biz_code") != 0:
        raise DeepSeekError(f"Platform business error {data.get('biz_code') if isinstance(data, dict) else '?'}")
    summary = data.get("biz_data") or {}
    if not isinstance(summary, dict):
        raise DeepSeekError("Platform response carried no wallet data")
    normal = _wallet_totals(summary.get("normal_wallets"))
    bonus = _wallet_totals(summary.get("bonus_wallets"))
    currencies = sorted(set(normal) | set(bonus))
    if not currencies:
        raise DeepSeekError("Platform response carried no wallets")
    currency = _preferred_currency({c: normal.get(c, Decimal(0)) + bonus.get(c, Decimal(0)) for c in currencies})
    topped = normal.get(currency, Decimal(0))
    granted = bonus.get(currency, Decimal(0))
    return DeepSeekBalance(
        currency=currency,
        total=topped + granted,
        topped_up=topped,
        granted=granted,
        is_available=None,
        fetched_at=time.time() if fetched_at is None else fetched_at,
        source="platform",
    )


class DeepSeekBalanceClient:
    """Query the remaining DeepSeek balance for one credential."""

    def __init__(
        self,
        credential: DeepSeekCredential,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        api_base: str = DEFAULT_API_BASE,
        platform_base: str | None = None,
    ) -> None:
        self.credential = credential
        self.timeout = timeout
        self.api_base = api_base.rstrip("/")
        self.platform_base = (platform_base or credential.base_url or DEFAULT_PLATFORM_BASE).rstrip("/")

    def read(self) -> DeepSeekBalance:
        if self.credential.kind == "api_key":
            payload = self._get(
                f"{self.api_base}/user/balance",
                {"Authorization": f"Bearer {self.credential.secret}"},
            )
            return parse_api_balance(payload)
        if self.credential.kind == "dsh_token":
            headers = dict(self.credential.extra_headers)
            headers["x-dsh-auth-token"] = self.credential.secret
            payload = self._get(f"{self.platform_base}/api/v0/users/get_user_summary", headers)
            return parse_platform_balance(payload)
        raise DeepSeekError(f"Unknown credential kind: {self.credential.kind}")

    def _get(self, url: str, headers: Mapping[str, str]) -> object:
        request = urllib.request.Request(url, method="GET")
        for name, value in headers.items():
            request.add_header(name, value)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(300).decode("utf-8", "replace")
            if exc.code in (401, 403):
                raise DeepSeekAuthError(self._auth_message(exc.code)) from None
            raise DeepSeekError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}: {detail[:120]}") from None
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"Network error reaching {urllib.parse.urlsplit(url).netloc}: {exc.reason}") from None
        except TimeoutError:
            raise DeepSeekError(f"Timed out reaching {urllib.parse.urlsplit(url).netloc}") from None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeepSeekError("Balance endpoint returned malformed JSON") from exc

    def _auth_message(self, status: int) -> str:
        if self.credential.kind == "dsh_token":
            return (
                f"DeepSeek 登录凭证已失效（HTTP {status}）。"
                "请在 DeepSeek Harness 里重新登录，或设置 DEEPSEEK_API_KEY。"
            )
        return (
            f"DeepSeek API Key 无效（HTTP {status}）。"
            "请检查 ~/.config/deepseek-display/api_key 或 DEEPSEEK_API_KEY。"
        )


def currency_symbol(currency: str) -> str:
    return {"CNY": "¥", "USD": "$"}.get(currency.upper(), currency.upper()[:1])


def format_money(value: Decimal | None) -> str:
    """Format a money amount with two decimals, trimming only if unreadable."""
    if value is None:
        return "--"
    text = f"{value:.2f}"
    return "-0.00" if text == "-0.00" else text


def summarize(balance: DeepSeekBalance) -> str:
    symbol = currency_symbol(balance.currency)
    parts = [f"{symbol}{format_money(balance.total)} 余额"]
    if balance.topped_up is not None:
        parts.append(f"充值 {symbol}{format_money(balance.topped_up)}")
    if balance.granted is not None:
        parts.append(f"赠送 {symbol}{format_money(balance.granted)}")
    stamp = time.strftime("%H:%M:%S", time.localtime(balance.fetched_at))
    return f"DeepSeek {balance.currency}: " + " / ".join(parts) + f" (读取于 {stamp})"
