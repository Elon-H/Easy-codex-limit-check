#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import shutil
import subprocess
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


DEFAULT_STATE_PATH = "~/Library/Caches/com.easy-codex-limit-check/state.json"
def to_iso8601(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def read_json(path: Optional[Path], default: Any = None) -> Any:
    if not path or not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def read_keychain_secret(service: str, account: str) -> Optional[str]:
    if not service or not account:
        return None
    cmd = [
        "security",
        "find-generic-password",
        "-w",
        "-s",
        service,
        "-a",
        account,
    ]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip()
    return value or None


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_iso8601(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1] + "+00:00").replace(tzinfo=None)
        return datetime.fromisoformat(value)
    except Exception:
        return None


def request_json(url: str, headers: Dict[str, str], timeout: int = 20) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def request_json_status(url: str, headers: Dict[str, str], timeout: int = 20) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, method="GET", headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8")
            return int(resp.status), json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"error": body[:500]}
        return int(exc.code), payload


def fetch_with_retries(base_url: str, paths: Sequence[str], params: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Optional[Dict[str, Any]]:
    for p in paths:
        try:
            from urllib.parse import urlencode

            filtered = {k: v for k, v in params.items() if v is not None}
            query = urlencode(filtered)
            sep = "&" if "?" in p else "?"
            url = f"{base_url}{p}{sep}{query}" if query else f"{base_url}{p}"
            return request_json(url, headers, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in {401, 403, 404}:
                body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
                if "invalid" in body.lower():
                    raise
            continue
        except Exception:
            continue
    return None


def extract_usage(payload: Any) -> Optional[float]:
    candidate = (
        "total_usage",
        "total_usage_usd",
        "total_cost",
        "cost",
        "subtotal",
        "amount",
        "usage",
    )

    if isinstance(payload, (int, float)):
        return float(payload)

    if isinstance(payload, dict):
        for key in candidate:
            if key in payload:
                val = safe_float(payload[key])
                if val is not None:
                    return val

        for key in ("data", "items", "results", "daily_costs"):
            if key in payload:
                val = extract_usage(payload[key])
                if val is not None:
                    return val

        for value in payload.values():
            val = extract_usage(value)
            if val is not None:
                return val
        return None

    if isinstance(payload, list):
        total = 0.0
        found = False
        for item in payload:
            val = extract_usage(item)
            if val is not None:
                total += val
                found = True
        return total if found else None
    return None


def compute_window(now: datetime, hours: int, *, weekday_start: int = 1) -> tuple[datetime, datetime]:
    if hours <= 0:
        raise ValueError("window_hours must be greater than 0")
    window_start = now.replace(minute=0, second=0, microsecond=0)
    start_hour = (window_start.hour // hours) * hours
    window_start = window_start.replace(hour=start_hour)
    window_end = window_start + timedelta(hours=hours)
    if window_end <= now:
        window_end = window_end + timedelta(hours=hours)
        window_start = window_end - timedelta(hours=hours)
    return window_start, window_end


def compute_week(now: datetime, weekday_start: int) -> tuple[datetime, datetime]:
    today_weekday = now.weekday()
    delta = (today_weekday - weekday_start) % 7
    start = now - timedelta(days=delta)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    if end <= now:
        end = end + timedelta(days=7)
        start = end - timedelta(days=7)
    return start, end


def parse_config(path: Optional[Path]) -> Dict[str, Any]:
    cfg = {
        "provider": "app_server",
        "five_hour_window_hours": 5,
        "week_window_days": 7,
        "week_start_weekday": 1,
        "state_file_ttl_seconds": 180,
        "five_hour_limit_usd": 0,
        "week_limit_usd": 0,
        "defaults": {
            "five_hour_limit_usd": 10.0,
            "week_limit_usd": 100.0,
        },
        "openai": {
            "api_base": "https://api.openai.com",
            "api_key_env": "OPENAI_API_KEY",
            "organization_id_env": "OPENAI_ORGANIZATION_ID",
            "timeout_seconds": 20,
            "keychain_service": "com.easy-codex-limit-check.openai",
            "keychain_account": "api_key",
        },
        "codex": {
            "api_base": "https://chatgpt.com/backend-api",
            "usage_path": "/wham/usage",
            "auth_file": "~/.codex/auth.json",
            "timeout_seconds": 20,
        },
        "app_server": {
            "command": "codex",
            "timeout_seconds": 20,
            "fallback_to_wham": True,
        },
        "manual": {
            "unit": "messages",
            "five_h": {
                "limit": None,
                "used": None,
                "remaining": None,
                "reset_at": None,
            },
            "week": {
                "limit": None,
                "used": None,
                "remaining": None,
                "reset_at": None,
            },
        },
    }
    loaded = read_json(path, default=None)
    if isinstance(loaded, dict):
        for k, v in loaded.items():
            if isinstance(v, dict):
                cfg[k] = {**cfg.get(k, {}), **v}
            else:
                cfg[k] = v
    return cfg


def build_state_value(
    used: Optional[float], limit: float, reset_at: datetime, now: datetime, label: str, unit: str = "USD"
) -> Dict[str, Any]:
    if used is None:
        return {
            "limit": limit,
            "used": None,
            "remaining": None,
            "reset_at": to_iso8601(reset_at),
            "unit": unit or "USD",
            "updated_at": to_iso8601(now),
            "label": label,
        }
    remaining = max(limit - used, 0)
    return {
        "limit": limit,
        "used": round(used, 6),
        "remaining": round(remaining, 6),
        "reset_at": to_iso8601(reset_at),
        "unit": unit or "USD",
        "updated_at": to_iso8601(now),
        "label": label,
    }


def build_openai_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    openai_cfg = cfg["openai"]
    api_key = os.getenv(openai_cfg.get("api_key_env", "OPENAI_API_KEY").strip(), "").strip()
    if not api_key:
        api_key = (
            read_keychain_secret(
                openai_cfg.get("keychain_service", "").strip(),
                openai_cfg.get("keychain_account", "").strip(),
            )
            or ""
        )
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required. Set it in environment and retry.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    org_env = openai_cfg.get("organization_id_env")
    if org_env:
        org = os.getenv(org_env, "").strip()
        if org:
            headers["OpenAI-Organization"] = org
    return headers


def read_codex_access_token(cfg: Dict[str, Any]) -> str:
    auth_file = Path(os.path.expanduser(cfg["codex"].get("auth_file", "~/.codex/auth.json"))).resolve()
    payload = read_json(auth_file, default={})
    if not isinstance(payload, dict):
        raise RuntimeError(f"Codex auth file is not readable: {auth_file}")
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError(f"Codex auth file has no tokens object: {auth_file}")
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError(f"Codex access token is missing: {auth_file}")
    return access_token.strip()


def build_codex_headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {read_codex_access_token(cfg)}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def fetch_codex_usage(cfg: Dict[str, Any]) -> Dict[str, Any]:
    base = cfg["codex"].get("api_base", "https://chatgpt.com/backend-api").rstrip("/")
    path = cfg["codex"].get("usage_path", "/wham/usage")
    timeout = int(cfg["codex"].get("timeout_seconds", 20))
    status, payload = request_json_status(f"{base}{path}", build_codex_headers(cfg), timeout)
    if status == 401 or status == 403:
        raise RuntimeError(f"Codex usage request was rejected with HTTP {status}; refresh Codex login and retry.")
    if status < 200 or status >= 300:
        raise RuntimeError(f"Codex usage request failed with HTTP {status}")
    if not isinstance(payload, dict):
        raise RuntimeError("Codex usage response was not a JSON object")
    return payload


def _app_server_command(cfg: Dict[str, Any]) -> list[str]:
    app_cfg = cfg.get("app_server", {})
    if not isinstance(app_cfg, dict):
        app_cfg = {}

    raw_command = app_cfg.get("command", "codex")
    if isinstance(raw_command, list):
        command = [str(part) for part in raw_command if str(part).strip()]
    else:
        command = shlex.split(str(raw_command or "codex"))
    if not command:
        command = ["codex"]

    if command[0] == "codex":
        resolved = shutil.which("codex")
        bundled = "/Applications/Codex.app/Contents/Resources/codex"
        if resolved:
            command[0] = resolved
        elif Path(bundled).exists():
            command[0] = bundled

    return command + ["app-server", "--listen", "stdio://"]


def _send_jsonl(proc: subprocess.Popen, payload: Dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("Codex app-server stdin is unavailable")
    proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def fetch_app_server_rate_limits(cfg: Dict[str, Any]) -> Dict[str, Any]:
    app_cfg = cfg.get("app_server", {})
    if not isinstance(app_cfg, dict):
        app_cfg = {}
    timeout = int(app_cfg.get("timeout_seconds", 20))
    command = _app_server_command(cfg)

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Codex app-server command was not found: {command[0]}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to start Codex app-server: {exc}") from exc

    try:
        _send_jsonl(
            proc,
            {
                "method": "initialize",
                "id": 0,
                "params": {
                    "clientInfo": {
                        "name": "easy-codex-limit-check",
                        "title": "Easy Codex Limit Check",
                        "version": "0.1.0",
                    }
                },
            },
        )
        _send_jsonl(proc, {"method": "initialized", "params": {}})
        _send_jsonl(proc, {"method": "account/rateLimits/read", "id": 1, "params": None})

        deadline = datetime.utcnow() + timedelta(seconds=timeout)
        while datetime.utcnow() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(f"Codex app-server exited early with code {proc.returncode}: {stderr.strip()}")

            remaining = max((deadline - datetime.utcnow()).total_seconds(), 0.0)
            ready, _, _ = select.select([proc.stdout], [], [], min(0.25, remaining))
            if not ready:
                continue

            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict) or message.get("id") != 1:
                continue
            if isinstance(message.get("error"), dict):
                err = message["error"]
                raise RuntimeError(err.get("message") or json.dumps(err, ensure_ascii=False))
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Codex app-server rate limit response had no result object")
            return result

        raise RuntimeError("Timed out waiting for Codex app-server rate limit response")
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass


def fetch_openai_subscription(cfg: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, float]:
    base = cfg["openai"]["api_base"].rstrip("/")
    timeout = int(cfg["openai"].get("timeout_seconds", 20))
    payload = fetch_with_retries(base, ["/v1/dashboard/billing/subscription"], {}, headers, timeout)
    if not isinstance(payload, dict):
        return {}
    out = {}
    for key in ("hard_limit_usd", "soft_limit_usd", "hard_limit", "soft_limit"):
        val = safe_float(payload.get(key))
        if val is not None:
            out[key] = val
    return out


def fetch_openai_usage(cfg: Dict[str, Any], headers: Dict[str, str], start: datetime, end: datetime) -> Optional[float]:
    base = cfg["openai"]["api_base"].rstrip("/")
    timeout = int(cfg["openai"].get("timeout_seconds", 20))
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    candidate_paths = [
        "/v1/dashboard/billing/usage",
        "/v1/organization/usage?bucket_width=1h",
    ]
    tried_any = False
    for path in candidate_paths:
        params = {"start_time": start_ts, "end_time": end_ts}
        if "dashboard/billing/usage" in path:
            params = {"start_date": start_date, "end_date": end_date}
        try:
            payload = fetch_with_retries(base, [path], params, headers, timeout)
        except Exception:
            payload = None
        if payload is not None:
            tried_any = True
        if not payload:
            continue
        total = extract_usage(payload)
        if total is not None:
            return total
    if not tried_any:
        raise RuntimeError("All usage endpoints failed")
    raise RuntimeError("Usage payloads returned no parsable usage")


def format_limit(cfg: Dict[str, Any], subscription: Dict[str, float], key: str) -> float:
    v = safe_float(cfg.get(key))
    if v and v > 0:
        return v
    if subscription:
        sub_v = safe_float(subscription.get("hard_limit_usd")) or safe_float(subscription.get("soft_limit_usd"))
        if sub_v and sub_v > 0:
            return sub_v
    default_key = "defaults"
    if isinstance(cfg.get(default_key), dict):
        return safe_float(cfg[default_key].get(key)) or 0.0
    return 0.0


def _coalesce_float(*candidates: Any) -> Optional[float]:
    for value in candidates:
        parsed = safe_float(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _clamp_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    percent = value * 100 if 0 <= value <= 1 else value
    return round(max(0.0, min(100.0, percent)), 2)


def _clamp_percent_points(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 2)


def _epoch_to_datetime(value: Any) -> Optional[datetime]:
    seconds = safe_float(value)
    if seconds is None:
        return None
    try:
        return datetime.utcfromtimestamp(seconds)
    except Exception:
        return None


def _percent_display_value(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if value == round(value):
        return float(round(value))
    return round(value, 2)


def _rate_limit_window_from_codex(window: Any, fallback_reset_at: datetime, now: datetime, label: str) -> Dict[str, Any]:
    if not isinstance(window, dict):
        window = {}
    used_percent = _clamp_percent(safe_float(window.get("used_percent")))
    remaining_percent = None if used_percent is None else _percent_display_value(100 - used_percent)
    reset_at = _epoch_to_datetime(window.get("reset_at")) or fallback_reset_at
    reset_after_seconds = safe_float(window.get("reset_after_seconds"))
    window_seconds = safe_float(window.get("limit_window_seconds"))
    return {
        "label": label,
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "reset_at": to_iso8601(reset_at),
        "reset_after_seconds": int(reset_after_seconds) if reset_after_seconds is not None else None,
        "window_seconds": int(window_seconds) if window_seconds is not None else None,
        "updated_at": to_iso8601(now),
    }


def _rate_limit_group_from_codex(
    name: str,
    payload: Any,
    now: datetime,
    five_end: datetime,
    week_end: datetime,
    metered_feature: Optional[str] = None,
) -> Dict[str, Any]:
    rate_limit = payload if isinstance(payload, dict) else {}
    return {
        "name": name,
        "metered_feature": metered_feature,
        "allowed": bool(rate_limit.get("allowed", True)),
        "limit_reached": bool(rate_limit.get("limit_reached", False)),
        "five_h": _rate_limit_window_from_codex(rate_limit.get("primary_window"), five_end, now, "5h"),
        "week": _rate_limit_window_from_codex(rate_limit.get("secondary_window"), week_end, now, "Weekly"),
        "updated_at": to_iso8601(now),
    }


def _rate_limit_window_from_app_server(window: Any, fallback_reset_at: datetime, now: datetime, label: str) -> Dict[str, Any]:
    if not isinstance(window, dict):
        window = {}
    # Codex App Server reports usedPercent as percentage points, e.g. 1 means 1%.
    used_percent = _clamp_percent_points(safe_float(window.get("usedPercent")))
    remaining_percent = None if used_percent is None else _percent_display_value(100 - used_percent)
    reset_at = _epoch_to_datetime(window.get("resetsAt")) or fallback_reset_at
    window_minutes = safe_float(window.get("windowDurationMins"))
    window_seconds = int(window_minutes * 60) if window_minutes is not None else None
    reset_after_seconds = max(0, int((reset_at - now).total_seconds())) if reset_at else None
    return {
        "label": label,
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "reset_at": to_iso8601(reset_at),
        "reset_after_seconds": reset_after_seconds,
        "window_seconds": window_seconds,
        "updated_at": to_iso8601(now),
    }


def _rate_limit_group_from_app_server(
    name: str,
    payload: Any,
    now: datetime,
    five_end: datetime,
    week_end: datetime,
) -> Dict[str, Any]:
    rate_limit = payload if isinstance(payload, dict) else {}
    limit_reached = rate_limit.get("rateLimitReachedType") is not None
    return {
        "name": name,
        "metered_feature": rate_limit.get("limitId") if isinstance(rate_limit.get("limitId"), str) else None,
        "allowed": not limit_reached,
        "limit_reached": limit_reached,
        "five_h": _rate_limit_window_from_app_server(rate_limit.get("primary"), five_end, now, "5h"),
        "week": _rate_limit_window_from_app_server(rate_limit.get("secondary"), week_end, now, "Weekly"),
        "updated_at": to_iso8601(now),
    }


def _rate_limit_group_is_usable(group: Dict[str, Any]) -> bool:
    five = group.get("five_h") if isinstance(group.get("five_h"), dict) else {}
    week = group.get("week") if isinstance(group.get("week"), dict) else {}
    return five.get("used_percent") is not None or week.get("used_percent") is not None


def _app_server_rate_limit_groups(payload: Dict[str, Any], now: datetime, five_end: datetime, week_end: datetime) -> list[Dict[str, Any]]:
    single = payload.get("rateLimits") if isinstance(payload.get("rateLimits"), dict) else None
    by_id = payload.get("rateLimitsByLimitId") if isinstance(payload.get("rateLimitsByLimitId"), dict) else None

    groups: list[Dict[str, Any]] = []
    primary_key = None
    primary = None

    if by_id:
        if isinstance(by_id.get("codex"), dict):
            primary_key = "codex"
            primary = by_id["codex"]
        elif single:
            primary = single
            limit_id = single.get("limitId")
            if isinstance(limit_id, str) and isinstance(by_id.get(limit_id), dict):
                primary_key = limit_id
        else:
            primary_key, primary = next(
                ((key, value) for key, value in by_id.items() if isinstance(value, dict)),
                (None, None),
            )
    elif single:
        primary = single

    if isinstance(primary, dict):
        groups.append(_rate_limit_group_from_app_server("Rate limits remaining", primary, now, five_end, week_end))

    if by_id:
        for key, value in by_id.items():
            if key == primary_key or not isinstance(value, dict):
                continue
            if single and primary_key is None and value.get("limitId") == single.get("limitId"):
                continue
            name = value.get("limitName") if isinstance(value.get("limitName"), str) and value.get("limitName") else str(key)
            groups.append(_rate_limit_group_from_app_server(name, value, now, five_end, week_end))

    groups = [group for group in groups if _rate_limit_group_is_usable(group)]
    if not groups:
        raise RuntimeError("Codex app-server returned no usable rate limit windows")
    return groups


def _credits_from_app_server(groups: list[Dict[str, Any]], raw_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = []
    single = raw_payload.get("rateLimits") if isinstance(raw_payload.get("rateLimits"), dict) else None
    if single:
        candidates.append(single.get("credits"))
    by_id = raw_payload.get("rateLimitsByLimitId") if isinstance(raw_payload.get("rateLimitsByLimitId"), dict) else None
    if by_id:
        candidates.extend(value.get("credits") for value in by_id.values() if isinstance(value, dict))

    for credits in candidates:
        if not isinstance(credits, dict):
            continue
        return {
            "has_credits": credits.get("hasCredits"),
            "unlimited": credits.get("unlimited"),
            "balance": credits.get("balance"),
        }
    return None


def _manual_percent(section_input: Dict[str, Any]) -> Optional[float]:
    percent = safe_float(section_input.get("remaining_percent"))
    if percent is None:
        percent = safe_float(section_input.get("percent"))
    if percent is not None:
        return _clamp_percent(percent)

    limit = safe_float(section_input.get("limit"))
    remaining = safe_float(section_input.get("remaining"))
    if limit and limit > 0 and remaining is not None:
        return _clamp_percent((remaining / limit) * 100)
    return None


def _rate_limit_window(
    section_input: Dict[str, Any],
    prev_section: Optional[Dict[str, Any]],
    fallback_reset_at: datetime,
    now: datetime,
    label: str,
) -> Dict[str, Any]:
    percent = _manual_percent(section_input)
    if percent is None and isinstance(prev_section, dict):
        percent = _clamp_percent(safe_float(prev_section.get("remaining_percent")))

    parsed_reset = parse_iso8601(section_input.get("reset_at"))
    prev_reset = parse_iso8601(prev_section.get("reset_at")) if isinstance(prev_section, dict) else None
    reset_at = parsed_reset or prev_reset or fallback_reset_at

    return {
        "label": label,
        "remaining_percent": percent,
        "reset_at": to_iso8601(reset_at),
        "updated_at": to_iso8601(now),
    }


def _prev_rate_limit_by_name(prev_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    groups = prev_state.get("rate_limits")
    if not isinstance(groups, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in groups:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "")
        if name:
            out[name] = item
    return out


def _resolve_manual_rate_limits(
    manual_cfg: Dict[str, Any],
    prev_state: Dict[str, Any],
    now: datetime,
    five_end: datetime,
    week_end: datetime,
    fallback_five: Optional[Dict[str, Any]] = None,
    fallback_week: Optional[Dict[str, Any]] = None,
) -> list[Dict[str, Any]]:
    raw_groups = manual_cfg.get("rate_limits")
    if not isinstance(raw_groups, list) or not raw_groups:
        raw_groups = [
            {
                "name": manual_cfg.get("title") or "Rate limits remaining",
                "five_h": fallback_five or manual_cfg.get("five_h", {}),
                "week": fallback_week or manual_cfg.get("week", {}),
            }
        ]

    previous = _prev_rate_limit_by_name(prev_state)
    resolved = []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("title") or "Rate limits remaining")
        prev_group = previous.get(name, {})
        five_input = raw.get("five_h") if isinstance(raw.get("five_h"), dict) else {}
        week_input = raw.get("week") if isinstance(raw.get("week"), dict) else {}
        five_prev = prev_group.get("five_h") if isinstance(prev_group.get("five_h"), dict) else None
        week_prev = prev_group.get("week") if isinstance(prev_group.get("week"), dict) else None
        resolved.append(
            {
                "name": name,
                "five_h": _rate_limit_window(five_input, five_prev, five_end, now, "5h"),
                "week": _rate_limit_window(week_input, week_prev, week_end, now, "Weekly"),
                "updated_at": to_iso8601(now),
            }
        )
    return resolved


def _resolve_manual_section(
    cfg: Dict[str, Any],
    manual_cfg: Dict[str, Any],
    section_key: str,
    window_reset_at: datetime,
    prev_section: Optional[Dict[str, Any]],
    now: datetime,
    fallback_limit_key: str,
    label: str,
) -> QuotaSection:
    section_input = {}
    if isinstance(manual_cfg.get(section_key), dict):
        section_input = manual_cfg[section_key]

    manual_unit = manual_cfg.get("unit")
    prev_unit = None
    if isinstance(prev_section, dict):
        prev_unit = prev_section.get("unit")
    unit = (
        manual_unit
        or (prev_unit if isinstance(prev_unit, str) else None)
        or "USD"
    )

    section_unit = section_input.get("unit")
    if isinstance(section_unit, str) and section_unit.strip():
        unit = section_unit

    limit = _coalesce_float(
        section_input.get("limit"),
        cfg.get(fallback_limit_key),
        cfg.get("defaults", {}).get(fallback_limit_key),
    )
    if limit is None:
        limit = 0.0

    used = safe_float(section_input.get("used"))
    remaining = safe_float(section_input.get("remaining"))

    if used is None and remaining is not None:
        used = max(limit - remaining, 0)

    if remaining is None and used is not None:
        remaining = max(limit - used, 0)

    if used is None and remaining is None:
        if isinstance(prev_section, dict):
            used = safe_float(prev_section.get("used"))
            remaining = safe_float(prev_section.get("remaining"))

    if used is None and remaining is not None:
        used = max(limit - remaining, 0)
    if remaining is None and used is not None:
        remaining = max(limit - used, 0)

    if remaining is not None:
        remaining = round(remaining, 6)
    if used is not None:
        used = round(used, 6)

    parsed_reset = parse_iso8601(section_input.get("reset_at"))
    prev_reset = None
    if isinstance(prev_section, dict):
        prev_reset = parse_iso8601(prev_section.get("reset_at"))
    reset_at = parsed_reset or prev_reset
    if reset_at is None:
        reset_at = window_reset_at

    return QuotaSection(
        limit=limit,
        used=used,
        reset_at=reset_at,
        updated_at=now,
        label=label,
        unit=str(unit),
    )


@dataclass
class QuotaSection:
    limit: float
    used: Optional[float]
    reset_at: datetime
    updated_at: datetime
    label: str
    unit: str = "USD"

    def dict(self) -> Dict[str, Any]:
        return build_state_value(self.used, self.limit, self.reset_at, self.updated_at, self.label, self.unit)


def resolve_manual_state(cfg: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow()
    state: Dict[str, Any] = {
        "source": {
            "provider": "manual",
            "api_base": None,
        },
        "window_version": 1,
        "state_file_ttl_seconds": int(cfg.get("state_file_ttl_seconds", 180)),
    }

    manual_cfg = cfg.get("manual", {})
    if not isinstance(manual_cfg, dict):
        manual_cfg = {}

    five_start, five_end = compute_window(now, int(cfg.get("five_hour_window_hours", 5)))
    week_start, week_end = compute_week(now, int(cfg.get("week_start_weekday", 1)))

    five = _resolve_manual_section(
        cfg,
        manual_cfg,
        "five_h",
        five_end,
        prev_state.get("five_h"),
        now,
        "five_hour_limit_usd",
        "five_h",
    )
    week = _resolve_manual_section(
        cfg,
        manual_cfg,
        "week",
        week_end,
        prev_state.get("week"),
        now,
        "week_limit_usd",
        "week",
    )

    state["five_h"] = five.dict()
    state["week"] = week.dict()
    state["rate_limits"] = _resolve_manual_rate_limits(
        manual_cfg,
        prev_state,
        now,
        five_end,
        week_end,
        state["five_h"],
        state["week"],
    )
    state["source"]["last_refresh_at"] = to_iso8601(now)
    state["source"]["refreshed"] = {
        "five_h_used_source": "manual",
        "week_used_source": "manual",
        "five_limit_usd": five.limit,
        "week_limit_usd": week.limit,
        "intervals": {
            "five_h_start": to_iso8601(five_start),
            "five_h_end": to_iso8601(five_end),
            "week_start": to_iso8601(week_start),
            "week_end": to_iso8601(week_end),
        },
    }
    return state


def resolve_codex_state(cfg: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow()
    five_start, five_end = compute_window(now, int(cfg.get("five_hour_window_hours", 5)))
    week_start, week_end = compute_week(now, int(cfg.get("week_start_weekday", 1)))
    payload = fetch_codex_usage(cfg)

    main_group = _rate_limit_group_from_codex(
        "Rate limits remaining",
        payload.get("rate_limit"),
        now,
        five_end,
        week_end,
    )
    groups = [main_group]
    raw_additional = payload.get("additional_rate_limits")
    if isinstance(raw_additional, list):
        for item in raw_additional:
            if not isinstance(item, dict):
                continue
            name = str(item.get("limit_name") or "Additional limit")
            metered_feature = item.get("metered_feature") if isinstance(item.get("metered_feature"), str) else None
            groups.append(
                _rate_limit_group_from_codex(
                    name,
                    item.get("rate_limit"),
                    now,
                    five_end,
                    week_end,
                    metered_feature,
                )
            )

    five_limit = 100.0
    week_limit = 100.0
    five_remaining = safe_float(main_group["five_h"].get("remaining_percent"))
    week_remaining = safe_float(main_group["week"].get("remaining_percent"))
    five_used = None if five_remaining is None else 100 - five_remaining
    week_used = None if week_remaining is None else 100 - week_remaining
    five = QuotaSection(five_limit, five_used, parse_iso8601(main_group["five_h"].get("reset_at")) or five_end, now, "five_h", "%")
    week = QuotaSection(week_limit, week_used, parse_iso8601(main_group["week"].get("reset_at")) or week_end, now, "week", "%")

    state: Dict[str, Any] = {
        "source": {
            "provider": "codex_wham",
            "api_base": cfg.get("codex", {}).get("api_base"),
            "last_refresh_at": to_iso8601(now),
            "refreshed": {
                "five_h_used_source": "codex_wham",
                "week_used_source": "codex_wham",
                "plan_type": payload.get("plan_type"),
                "intervals": {
                    "five_h_start": to_iso8601(five_start),
                    "five_h_end": to_iso8601(five_end),
                    "week_start": to_iso8601(week_start),
                    "week_end": to_iso8601(week_end),
                },
            },
        },
        "window_version": 2,
        "state_file_ttl_seconds": int(cfg.get("state_file_ttl_seconds", 180)),
        "five_h": five.dict(),
        "week": week.dict(),
        "rate_limits": groups,
    }

    credits = payload.get("credits")
    if isinstance(credits, dict):
        state["credits"] = {
            "has_credits": credits.get("has_credits"),
            "unlimited": credits.get("unlimited"),
            "overage_limit_reached": credits.get("overage_limit_reached"),
            "balance": credits.get("balance"),
            "approx_local_messages": credits.get("approx_local_messages"),
            "approx_cloud_messages": credits.get("approx_cloud_messages"),
        }
    return state


def resolve_app_server_state(cfg: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow()
    five_start, five_end = compute_window(now, int(cfg.get("five_hour_window_hours", 5)))
    week_start, week_end = compute_week(now, int(cfg.get("week_start_weekday", 1)))
    payload = fetch_app_server_rate_limits(cfg)
    groups = _app_server_rate_limit_groups(payload, now, five_end, week_end)
    main_group = groups[0]

    five_limit = 100.0
    week_limit = 100.0
    five_remaining = safe_float(main_group["five_h"].get("remaining_percent"))
    week_remaining = safe_float(main_group["week"].get("remaining_percent"))
    five_used = None if five_remaining is None else 100 - five_remaining
    week_used = None if week_remaining is None else 100 - week_remaining
    five = QuotaSection(five_limit, five_used, parse_iso8601(main_group["five_h"].get("reset_at")) or five_end, now, "five_h", "%")
    week = QuotaSection(week_limit, week_used, parse_iso8601(main_group["week"].get("reset_at")) or week_end, now, "week", "%")

    plan_type = None
    raw_main = payload.get("rateLimits") if isinstance(payload.get("rateLimits"), dict) else None
    if raw_main:
        plan_type = raw_main.get("planType")

    state: Dict[str, Any] = {
        "source": {
            "provider": "app_server",
            "api_base": "codex app-server stdio",
            "last_refresh_at": to_iso8601(now),
            "refreshed": {
                "five_h_used_source": "app_server",
                "week_used_source": "app_server",
                "plan_type": plan_type,
                "intervals": {
                    "five_h_start": to_iso8601(five_start),
                    "five_h_end": to_iso8601(five_end),
                    "week_start": to_iso8601(week_start),
                    "week_end": to_iso8601(week_end),
                },
            },
        },
        "window_version": 2,
        "state_file_ttl_seconds": int(cfg.get("state_file_ttl_seconds", 180)),
        "five_h": five.dict(),
        "week": week.dict(),
        "rate_limits": groups,
    }

    credits = _credits_from_app_server(groups, payload)
    if credits:
        state["credits"] = credits
    return state


def resolve_app_server_with_fallback(cfg: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return resolve_app_server_state(cfg, prev_state)
    except Exception as app_exc:
        app_cfg = cfg.get("app_server", {})
        fallback_enabled = True
        if isinstance(app_cfg, dict):
            fallback_enabled = bool(app_cfg.get("fallback_to_wham", True))
        if not fallback_enabled:
            raise
        try:
            fallback = resolve_codex_state(cfg, prev_state)
        except Exception as wham_exc:
            raise RuntimeError(f"app_server failed: {app_exc}; codex_wham fallback failed: {wham_exc}") from wham_exc
        source = fallback.setdefault("source", {})
        refreshed = source.setdefault("refreshed", {})
        if isinstance(refreshed, dict):
            refreshed["fallback_from"] = "app_server"
            refreshed["fallback_error"] = str(app_exc)
        return fallback


def resolve_state(cfg: Dict[str, Any], prev_state: Dict[str, Any]) -> Dict[str, Any]:
    provider = str(cfg.get("provider", "openai")).strip().lower()
    if provider in {"app_server", "codex_app_server"}:
        return resolve_app_server_with_fallback(cfg, prev_state)
    if provider in {"codex", "codex_wham", "chatgpt"}:
        return resolve_codex_state(cfg, prev_state)
    if provider == "manual":
        return resolve_manual_state(cfg, prev_state)

    state: Dict[str, Any] = {
        "source": {
            "provider": cfg.get("provider", "openai"),
            "api_base": cfg.get("openai", {}).get("api_base"),
        },
        "window_version": 1,
        "state_file_ttl_seconds": int(cfg.get("state_file_ttl_seconds", 180)),
    }

    headers = build_openai_headers(cfg)
    subscription = fetch_openai_subscription(cfg, headers)
    now = datetime.utcnow()
    five_start, five_end = compute_window(now, int(cfg.get("five_hour_window_hours", 5)))
    week_start, week_end = compute_week(now, int(cfg.get("week_start_weekday", 1)))

    five_limit = float(format_limit(cfg, subscription, "five_hour_limit_usd"))
    week_limit = float(format_limit(cfg, subscription, "week_limit_usd"))

    errors = []
    now = datetime.utcnow()
    five_used = None
    week_used = None
    try:
        five_used = fetch_openai_usage(cfg, headers, five_start, now)
    except Exception as exc:
        errors.append(f"five_hour_fetch_failed:{exc}")
    try:
        week_used = fetch_openai_usage(cfg, headers, week_start, now)
    except Exception as exc:
        errors.append(f"week_fetch_failed:{exc}")

    sections = {}
    if five_used is None and prev_state.get("five_h", {}).get("used") is not None:
        five = QuotaSection(five_limit, prev_state["five_h"].get("used"), parse_iso8601(prev_state["five_h"].get("reset_at")) or five_end, now, "five_h")
    else:
        five = QuotaSection(five_limit, five_used, five_end, now, "five_h")
    if week_used is None and prev_state.get("week", {}).get("used") is not None:
        week = QuotaSection(week_limit, prev_state["week"].get("used"), parse_iso8601(prev_state["week"].get("reset_at")) or week_end, now, "week")
    else:
        week = QuotaSection(week_limit, week_used, week_end, now, "week")

    sections["five_h"] = five.dict()
    sections["week"] = week.dict()
    state.update(sections)

    if errors:
        state["error"] = {
            "message": "; ".join(errors),
            "updated_at": to_iso8601(now),
            "previous_successful_refresh": prev_state.get("source", {}).get("last_refresh_at"),
        }

    state["source"]["last_refresh_at"] = to_iso8601(now)
    state["source"]["refreshed"] = {
        "five_h_used_source": "api" if five_used is not None else "cache",
        "week_used_source": "api" if week_used is not None else "cache",
        "five_limit_usd": five_limit,
        "week_limit_usd": week_limit,
        "intervals": {
            "five_h_start": to_iso8601(five_start),
            "five_h_end": to_iso8601(five_end),
            "week_start": to_iso8601(week_start),
            "week_end": to_iso8601(week_end),
        },
    }

    return state


def provider_api_base(cfg: Dict[str, Any]) -> Optional[str]:
    provider = str(cfg.get("provider", "openai")).strip().lower()
    if provider in {"app_server", "codex_app_server"}:
        return "codex app-server stdio"
    if provider in {"codex", "codex_wham", "chatgpt"}:
        return cfg.get("codex", {}).get("api_base")
    return cfg.get("openai", {}).get("api_base")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch quota information and write shared state for the menu-bar widget."
    )
    parser.add_argument(
        "--state-path",
        default=DEFAULT_STATE_PATH,
        help="Path to state json file written by the plugin and read by the menu-bar app.",
    )
    parser.add_argument("--config", default=None, help="Path to config JSON override.")
    parser.add_argument("--provider", choices=["openai", "manual", "codex_wham", "app_server"], help="Override provider.")
    parser.add_argument("--five-limit", type=float, default=None, help="Override 5h limit.")
    parser.add_argument("--week-limit", type=float, default=None, help="Override week limit.")
    parser.add_argument("--unit", default=None, help="Manual mode unit label, e.g. messages.")
    parser.add_argument("--five-used", type=float, default=None, help="Manual mode: 5h used.")
    parser.add_argument("--week-used", type=float, default=None, help="Manual mode: week used.")
    parser.add_argument("--five-remaining", type=float, default=None, help="Manual mode: 5h remaining.")
    parser.add_argument("--week-remaining", type=float, default=None, help="Manual mode: week remaining.")
    parser.add_argument(
        "--five-reset-at",
        default=None,
        help="Manual mode: 5h reset time (ISO8601).",
    )
    parser.add_argument(
        "--week-reset-at",
        default=None,
        help="Manual mode: week reset time (ISO8601).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print resolved state but do not write file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = parse_config(Path(args.config).expanduser().resolve() if args.config else None)
    if args.five_limit is not None:
        cfg["five_hour_limit_usd"] = args.five_limit
    if args.week_limit is not None:
        cfg["week_limit_usd"] = args.week_limit
    if args.provider:
        cfg["provider"] = args.provider

    manual_section = cfg.setdefault("manual", {})
    if not isinstance(manual_section, dict):
        manual_section = {}
        cfg["manual"] = manual_section
    if args.unit is not None:
        manual_section["unit"] = args.unit
    if args.five_used is not None or args.week_used is not None or args.five_remaining is not None or args.week_remaining is not None or args.five_reset_at is not None or args.week_reset_at is not None:
        five_manual = manual_section.setdefault("five_h", {})
        week_manual = manual_section.setdefault("week", {})
        if not isinstance(five_manual, dict):
            five_manual = {}
            manual_section["five_h"] = five_manual
        if not isinstance(week_manual, dict):
            week_manual = {}
            manual_section["week"] = week_manual
        if args.five_used is not None:
            five_manual["used"] = args.five_used
        if args.five_remaining is not None:
            five_manual["remaining"] = args.five_remaining
        if args.five_reset_at is not None:
            five_manual["reset_at"] = args.five_reset_at
        if args.week_used is not None:
            week_manual["used"] = args.week_used
        if args.week_remaining is not None:
            week_manual["remaining"] = args.week_remaining
        if args.week_reset_at is not None:
            week_manual["reset_at"] = args.week_reset_at

    state_path = Path(os.path.expanduser(args.state_path)).resolve()
    prev_state = read_json(state_path, default={})
    if not isinstance(prev_state, dict):
        prev_state = {}

    try:
        resolved = resolve_state(cfg, prev_state)
    except Exception as exc:
        error_state = {
            "source": {
                "provider": cfg.get("provider", "openai"),
                "api_base": provider_api_base(cfg),
                "last_error": str(exc),
            },
            "window_version": 1,
            "state_file_ttl_seconds": int(cfg.get("state_file_ttl_seconds", 180)),
            "five_h": prev_state.get("five_h"),
            "week": prev_state.get("week"),
            "rate_limits": prev_state.get("rate_limits"),
            "credits": prev_state.get("credits"),
            "error": {
                "message": str(exc),
                "updated_at": to_iso8601(datetime.utcnow()),
            },
        }
        if prev_state.get("five_h") is None and prev_state.get("week") is None:
            print(json.dumps(error_state, ensure_ascii=False, indent=2))
            return 1
        resolved = error_state

    if args.dry_run:
        print(json.dumps(resolved, ensure_ascii=False, indent=2))
    else:
        write_json(state_path, resolved)
        print(json.dumps({"status": "ok", "state_path": str(state_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
