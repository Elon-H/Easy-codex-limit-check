#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import shlex
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


DEFAULT_CONFIG_PATH = "~/Library/Application Support/com.easy-codex-limit-check/config.json"
DEFAULT_APPROVAL_STATE_PATH = "~/Library/Caches/com.easy-codex-limit-check/approval_state.json"
DEFAULT_APPROVAL_DECISIONS_PATH = "~/Library/Caches/com.easy-codex-limit-check/approval_decisions.jsonl"

MODERN_COMMAND = "item/commandExecution/requestApproval"
MODERN_FILE_CHANGE = "item/fileChange/requestApproval"
MODERN_PERMISSIONS = "item/permissions/requestApproval"
LEGACY_EXEC = "execCommandApproval"
LEGACY_PATCH = "applyPatchApproval"
ROLLOUT_PENDING_TOOL = "rollout/pendingToolApproval"
BUNDLED_CODEX_EXECUTABLES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "/Applications/Codex.app/Contents/Resources/codex",
)

DEFAULT_THREAD_SOURCE_KINDS = [
    "cli",
    "vscode",
    "exec",
    "appServer",
    "subAgent",
    "subAgentReview",
    "subAgentCompact",
    "subAgentThreadSpawn",
    "subAgentOther",
    "unknown",
]

SUPPORTED_APPROVAL_METHODS = {
    MODERN_COMMAND,
    MODERN_FILE_CHANGE,
    MODERN_PERMISSIONS,
    LEGACY_EXEC,
    LEGACY_PATCH,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def parse_config(path: Optional[Path]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "app_server": {
            "command": "codex",
            "timeout_seconds": 20,
        },
        "approvals": {
            "enabled": True,
            "command": None,
            "transport": "auto",
            "poll_interval_seconds": 2.0,
            "decision_poll_interval_seconds": 0.25,
            "thread_list_limit": 50,
            "thread_source_kinds": DEFAULT_THREAD_SOURCE_KINDS,
            "rollout_scan_enabled": True,
            "rollout_scan_recent_seconds": 21600,
            "rollout_scan_max_bytes": 2097152,
            "notify": True,
            "pulse": True,
            "reconnect_delay_seconds": 5.0,
        },
    }
    loaded = read_json(path, default=None)
    if isinstance(loaded, dict):
        for key, value in loaded.items():
            if isinstance(value, dict):
                existing = cfg.get(key)
                cfg[key] = {**existing, **value} if isinstance(existing, dict) else value
            else:
                cfg[key] = value
    return cfg


def app_server_command(cfg: Dict[str, Any], transport: str = "stdio") -> list[str]:
    approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    app_cfg = cfg.get("app_server") if isinstance(cfg.get("app_server"), dict) else {}
    raw_command = approval_cfg.get("command") or app_cfg.get("command") or "codex"

    if isinstance(raw_command, str):
        command = shlex.split(raw_command)
    elif isinstance(raw_command, list) and all(isinstance(part, str) for part in raw_command):
        command = raw_command
    else:
        raise RuntimeError("approvals.command must be a string or list of strings")

    if not command:
        raise RuntimeError("approvals.command is empty")

    if command[0] == "codex":
        resolved = shutil.which("codex")
        if resolved:
            command[0] = resolved
        else:
            for bundled in BUNDLED_CODEX_EXECUTABLES:
                if os.path.exists(bundled):
                    command[0] = bundled
                    break

    if transport == "proxy":
        return command + ["app-server", "proxy"]
    return command + ["app-server", "--listen", "stdio://"]


def request_id_key(value: Any) -> str:
    return str(value)


def stringify_command(command: Any) -> Optional[str]:
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        parts = [str(part) for part in command]
        return " ".join(shlex.quote(part) for part in parts)
    return None


def short_text(value: Any, limit: int = 160) -> Optional[str]:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def thread_title(thread: Dict[str, Any]) -> Optional[str]:
    for key in ("title", "name"):
        value = thread.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    preview = thread.get("preview")
    if isinstance(preview, str):
        return short_text(preview, 80)
    if isinstance(preview, dict):
        for key in ("title", "text", "summary"):
            value = preview.get(key)
            if isinstance(value, str) and value.strip():
                return short_text(value, 80)
    return None


def active_flags(thread: Dict[str, Any]) -> list[str]:
    status = thread.get("status")
    if not isinstance(status, dict):
        return []
    flags = status.get("activeFlags")
    if isinstance(flags, list):
        return [flag for flag in flags if isinstance(flag, str)]
    return []


def is_waiting_on_approval(thread: Dict[str, Any]) -> bool:
    return "waitingOnApproval" in active_flags(thread)


def parse_timestamp_seconds(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def codex_home_path(cfg: Dict[str, Any]) -> Path:
    approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    raw = approval_cfg.get("codex_home") or os.environ.get("CODEX_HOME") or "~/.codex"
    return Path(os.path.expanduser(str(raw))).resolve()


def read_tail_text(path: Path, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if start > 0:
        parts = text.split("\n", 1)
        return parts[1] if len(parts) == 2 else ""
    return text


def recent_rollout_threads(cfg: Dict[str, Any]) -> list[Dict[str, Any]]:
    approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    codex_home = codex_home_path(cfg)
    state_db = Path(os.path.expanduser(str(approval_cfg.get("state_db_path") or codex_home / "state_5.sqlite")))
    if not state_db.exists():
        return []

    recent_seconds = int(approval_cfg.get("rollout_scan_recent_seconds", 21600))
    limit = int(approval_cfg.get("thread_list_limit", 50))
    updated_after = int(time.time()) - max(recent_seconds, 60)

    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=1.0)
    try:
        rows = conn.execute(
            """
            select id, title, cwd, rollout_path, updated_at
            from threads
            where archived = 0
              and rollout_path != ''
              and updated_at >= ?
            order by updated_at desc
            limit ?
            """,
            (updated_after, limit),
        ).fetchall()
    finally:
        conn.close()

    out = []
    for thread_id, title, cwd, rollout_path, updated_at in rows:
        path = Path(str(rollout_path)).expanduser()
        if path.exists():
            out.append(
                {
                    "id": str(thread_id),
                    "title": str(title or ""),
                    "cwd": str(cwd or ""),
                    "rollout_path": path,
                    "updated_at": updated_at,
                }
            )
    return out


def parse_tool_arguments(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def pending_escalated_calls_from_rollout(
    thread: Dict[str, Any],
    max_bytes: int,
    recent_seconds: int,
) -> Dict[str, Dict[str, Any]]:
    path = thread.get("rollout_path")
    if not isinstance(path, Path) or not path.exists():
        return {}

    now = time.time()
    output_call_ids: set[str] = set()
    calls: Dict[str, Dict[str, Any]] = {}

    for raw_line in read_tail_text(path, max_bytes).splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "response_item":
            item_type = payload.get("type")
            call_id = payload.get("call_id")
            if item_type == "function_call_output" and isinstance(call_id, str):
                output_call_ids.add(call_id)
                continue
            if item_type != "function_call" or not isinstance(call_id, str):
                continue
            name = payload.get("name")
            arguments = parse_tool_arguments(payload.get("arguments"))
            if name != "exec_command" or arguments.get("sandbox_permissions") != "require_escalated":
                continue
            timestamp_seconds = parse_timestamp_seconds(event.get("timestamp"))
            if timestamp_seconds is not None and now - timestamp_seconds > recent_seconds:
                continue
            command = stringify_command(arguments.get("cmd"))
            if command is None:
                command = short_text(arguments.get("cmd"), 160)
            reason = arguments.get("justification") if isinstance(arguments.get("justification"), str) else None
            summary = short_text(command, 140) or short_text(reason, 140) or "Codex needs approval"
            created_at = event.get("timestamp") if isinstance(event.get("timestamp"), str) else utc_now_iso()
            calls[call_id] = {
                "id": f"rollout-{call_id}",
                "method": ROLLOUT_PENDING_TOOL,
                "kind": "desktopApproval",
                "title": "Codex desktop approval",
                "summary": summary,
                "detail": "Open Codex to approve or deny this request.",
                "thread_id": thread.get("id"),
                "thread_title": short_text(thread.get("title"), 90),
                "cwd": thread.get("cwd"),
                "command": command,
                "reason": reason,
                "created_at": created_at,
                "supports_direct_decision": False,
                "decisions": [],
                "source": "rollout_scan",
            }
        elif event_type == "event_msg":
            call_id = payload.get("call_id")
            payload_type = payload.get("type")
            if isinstance(call_id, str) and isinstance(payload_type, str) and payload_type.endswith("_end"):
                output_call_ids.add(call_id)

    return {approval["id"]: approval for call_id, approval in calls.items() if call_id not in output_call_ids}


def scan_rollout_pending_approvals(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    if approval_cfg.get("rollout_scan_enabled") is False:
        return {}
    max_bytes = int(approval_cfg.get("rollout_scan_max_bytes", 2097152))
    recent_seconds = int(approval_cfg.get("rollout_scan_recent_seconds", 21600))
    out: Dict[str, Dict[str, Any]] = {}
    for thread in recent_rollout_threads(cfg):
        out.update(pending_escalated_calls_from_rollout(thread, max_bytes, recent_seconds))
    return out


def approval_identity(method: str, params: Dict[str, Any], server_request_id: Any) -> str:
    thread_id = params.get("threadId") or params.get("conversationId") or ""
    turn_id = params.get("turnId") or ""
    item_id = params.get("itemId") or params.get("callId") or ""
    approval_id = params.get("approvalId") or ""
    raw = json.dumps(
        [method, thread_id, turn_id, item_id, approval_id, request_id_key(server_request_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def decision_options_for(method: str) -> list[Dict[str, str]]:
    if method == MODERN_PERMISSIONS:
        return [
            {"id": "grantTurn", "label": "Grant for Turn"},
            {"id": "grantSession", "label": "Grant for Session"},
            {"id": "decline", "label": "Deny"},
        ]
    return [
        {"id": "accept", "label": "Approve"},
        {"id": "acceptForSession", "label": "Approve for Session"},
        {"id": "decline", "label": "Deny"},
        {"id": "cancel", "label": "Cancel Turn"},
    ]


def normalize_approval_request(
    method: str,
    params: Dict[str, Any],
    server_request_id: Any,
    thread_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if method not in SUPPORTED_APPROVAL_METHODS:
        raise ValueError(f"Unsupported approval method: {method}")

    thread_metadata = thread_metadata or {}
    thread_id = params.get("threadId") or params.get("conversationId")
    turn_id = params.get("turnId")
    item_id = params.get("itemId") or params.get("callId")
    approval_id = params.get("approvalId")
    cwd = params.get("cwd") or thread_metadata.get("cwd")
    reason = params.get("reason")

    command = None
    grant_root = params.get("grantRoot")
    detail = None
    kind = "approval"
    title = "Codex approval"

    if method == MODERN_COMMAND:
        kind = "command"
        title = "Command approval"
        command = stringify_command(params.get("command"))
        network = params.get("networkApprovalContext")
        if isinstance(network, dict):
            host = network.get("host")
            proto = network.get("protocol")
            detail = f"Network access: {proto}://{host}" if host else "Network access"
    elif method == LEGACY_EXEC:
        kind = "command"
        title = "Command approval"
        command = stringify_command(params.get("command"))
    elif method == MODERN_FILE_CHANGE:
        kind = "fileChange"
        title = "File change approval"
        detail = f"Write access under {grant_root}" if grant_root else "File changes requested"
    elif method == LEGACY_PATCH:
        kind = "fileChange"
        title = "File change approval"
        changes = params.get("fileChanges")
        if isinstance(changes, dict):
            detail = f"{len(changes)} file change(s)"
    elif method == MODERN_PERMISSIONS:
        kind = "permissions"
        title = "Permission approval"
        permissions = params.get("permissions")
        if isinstance(permissions, dict):
            labels = []
            if permissions.get("fileSystem"):
                labels.append("filesystem")
            if permissions.get("network"):
                labels.append("network")
            detail = "Permissions: " + ", ".join(labels) if labels else "Additional permissions"

    summary = short_text(command, 140) if command else None
    if not summary:
        summary = short_text(reason, 140) or short_text(detail, 140) or title

    approval = {
        "id": approval_identity(method, params, server_request_id),
        "server_request_id": server_request_id,
        "method": method,
        "kind": kind,
        "title": title,
        "summary": summary,
        "detail": detail,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "item_id": item_id,
        "approval_id": approval_id,
        "thread_title": thread_title(thread_metadata),
        "cwd": cwd,
        "command": command,
        "reason": reason,
        "grant_root": grant_root,
        "created_at": utc_now_iso(),
        "supports_direct_decision": True,
        "decisions": decision_options_for(method),
        "raw_params": params,
    }
    return {key: value for key, value in approval.items() if value is not None}


def decision_response_for(approval: Dict[str, Any], decision: str) -> Dict[str, Any]:
    method = approval.get("method")

    if method in {MODERN_COMMAND, MODERN_FILE_CHANGE}:
        if decision not in {"accept", "acceptForSession", "decline", "cancel"}:
            raise ValueError(f"Unsupported decision for {method}: {decision}")
        return {"decision": decision}

    if method in {LEGACY_EXEC, LEGACY_PATCH}:
        mapping = {
            "accept": "approved",
            "acceptForSession": "approved_for_session",
            "decline": "denied",
            "cancel": "abort",
        }
        mapped = mapping.get(decision)
        if not mapped:
            raise ValueError(f"Unsupported decision for {method}: {decision}")
        return {"decision": mapped}

    if method == MODERN_PERMISSIONS:
        raw_params = approval.get("raw_params") if isinstance(approval.get("raw_params"), dict) else {}
        if decision == "grantTurn":
            return {"permissions": raw_params.get("permissions") or {}, "scope": "turn"}
        if decision == "grantSession":
            return {"permissions": raw_params.get("permissions") or {}, "scope": "session"}
        if decision == "decline":
            return {"permissions": {}, "scope": "turn"}
        raise ValueError(f"Unsupported decision for {method}: {decision}")

    raise ValueError(f"Unsupported approval method: {method}")


class AppServerApprovalWatcher:
    def __init__(self, cfg: Dict[str, Any], state_path: Path, decisions_path: Path) -> None:
        self.cfg = cfg
        self.approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
        self.state_path = state_path
        self.decisions_path = decisions_path
        self.proc: Optional[subprocess.Popen[str]] = None
        self.next_id = 1
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.scanned_pending: Dict[str, Dict[str, Any]] = {}
        self.thread_metadata: Dict[str, Dict[str, Any]] = {}
        self.resumed_threads: set[str] = set()
        self.decision_offset = 0
        self.last_error: Optional[str] = None
        self.last_scan_error: Optional[str] = None
        self.transport = "stdio"
        self.source = "codex app-server stdio"

    @property
    def poll_interval(self) -> float:
        return float(self.approval_cfg.get("poll_interval_seconds", 2.0))

    @property
    def decision_poll_interval(self) -> float:
        return float(self.approval_cfg.get("decision_poll_interval_seconds", 0.25))

    @property
    def timeout(self) -> float:
        app_cfg = self.cfg.get("app_server") if isinstance(self.cfg.get("app_server"), dict) else {}
        return float(self.approval_cfg.get("timeout_seconds") or app_cfg.get("timeout_seconds") or 20)

    def transport_candidates(self) -> list[str]:
        raw = str(self.approval_cfg.get("transport", "auto")).strip().lower()
        if raw == "proxy":
            return ["proxy"]
        if raw in {"stdio", "listen", "app_server"}:
            return ["stdio"]
        return ["proxy", "stdio"]

    def start_with_transport(self, transport: str) -> None:
        command = app_server_command(self.cfg, transport)
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.transport = transport
        self.source = "codex app-server proxy" if transport == "proxy" else "codex app-server stdio"
        self.call(
            "initialize",
            {
                "clientInfo": {
                    "name": "easy-codex-limit-check-approval-watcher",
                    "title": "Easy Codex Limit Check Approval Watcher",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
            timeout=self.timeout,
        )
        self.send_notification("initialized", {})

    def start(self) -> None:
        errors = []
        for transport in self.transport_candidates():
            try:
                self.start_with_transport(transport)
                return
            except Exception as exc:
                errors.append(f"{transport}: {exc}")
                self.stop()
        raise RuntimeError("Failed to start Codex app-server approval watcher: " + "; ".join(errors))

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def send(self, payload: Dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("Codex app-server stdin is unavailable")
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        self.send({"method": method, "params": params})

    def send_request(self, method: str, params: Any) -> int:
        req_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": req_id, "params": params})
        return req_id

    def read_message(self, timeout: float) -> Optional[Dict[str, Any]]:
        if not self.proc or not self.proc.stdout:
            raise RuntimeError("Codex app-server stdout is unavailable")
        if self.proc.poll() is not None:
            stderr = ""
            if self.proc.stderr:
                try:
                    stderr = self.proc.stderr.read()
                except Exception:
                    stderr = ""
            raise RuntimeError(f"Codex app-server exited with code {self.proc.returncode}: {stderr.strip()}")
        ready, _, _ = select.select([self.proc.stdout], [], [], max(timeout, 0.0))
        if not ready:
            return None
        line = self.proc.stdout.readline()
        if not line:
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def call(self, method: str, params: Any, timeout: float) -> Dict[str, Any]:
        req_id = self.send_request(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.read_message(min(0.2, max(deadline - time.monotonic(), 0.0)))
            if not message:
                self.consume_decisions()
                continue
            if self.is_response_for(message, req_id):
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            self.handle_message(message)
            self.consume_decisions()
        raise RuntimeError(f"Timed out waiting for {method}")

    @staticmethod
    def is_response_for(message: Dict[str, Any], req_id: int) -> bool:
        return "id" in message and "method" not in message and request_id_key(message.get("id")) == str(req_id)

    def handle_message(self, message: Dict[str, Any]) -> None:
        method = message.get("method")
        if not isinstance(method, str):
            return
        if "id" in message:
            self.handle_server_request(message)
        else:
            self.handle_notification(method, message.get("params"))

    def handle_server_request(self, message: Dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params")
        server_request_id = message.get("id")
        if not isinstance(method, str):
            return
        if method not in SUPPORTED_APPROVAL_METHODS:
            self.send({"id": server_request_id, "error": {"code": -32601, "message": f"Unsupported request: {method}"}})
            return
        if not isinstance(params, dict):
            self.send({"id": server_request_id, "error": {"code": -32602, "message": "Approval params must be an object"}})
            return

        thread_id = params.get("threadId") or params.get("conversationId")
        metadata = self.thread_metadata.get(thread_id, {}) if isinstance(thread_id, str) else {}
        approval = normalize_approval_request(method, params, server_request_id, metadata)
        self.pending[approval["id"]] = approval
        self.last_error = None
        self.write_state()

    def handle_notification(self, method: str, params: Any) -> None:
        if method in {"thread/statusChanged", "thread/status/changed"} and isinstance(params, dict):
            thread_id = params.get("threadId")
            status = params.get("status")
            if isinstance(thread_id, str) and isinstance(status, dict):
                metadata = self.thread_metadata.setdefault(thread_id, {"id": thread_id})
                metadata["status"] = status
                if "waitingOnApproval" not in active_flags(metadata):
                    self.drop_pending_for_thread(thread_id)
        elif method == "serverRequest/resolved" and isinstance(params, dict):
            self.drop_pending_for_server_request(params.get("requestId"), params.get("threadId"))
        elif method == "turn/completed" and isinstance(params, dict):
            thread_id = params.get("threadId")
            turn_id = params.get("turnId")
            if isinstance(thread_id, str):
                self.drop_pending_for_thread(thread_id, turn_id if isinstance(turn_id, str) else None)

    def drop_pending_for_thread(self, thread_id: str, turn_id: Optional[str] = None) -> None:
        removed = False
        for approval_id, approval in list(self.pending.items()):
            if approval.get("thread_id") != thread_id:
                continue
            if turn_id and approval.get("turn_id") != turn_id:
                continue
            self.pending.pop(approval_id, None)
            removed = True
        if removed:
            self.write_state()

    def drop_pending_for_server_request(self, server_request_id: Any, thread_id: Any = None) -> None:
        removed = False
        for approval_id, approval in list(self.pending.items()):
            if request_id_key(approval.get("server_request_id")) != request_id_key(server_request_id):
                continue
            if isinstance(thread_id, str) and approval.get("thread_id") != thread_id:
                continue
            self.pending.pop(approval_id, None)
            removed = True
        if removed:
            self.write_state()

    def scan_rollout_fallback(self) -> None:
        try:
            self.scanned_pending = scan_rollout_pending_approvals(self.cfg)
            self.last_scan_error = None
        except Exception as exc:
            self.last_scan_error = str(exc)

    def poll_threads(self) -> None:
        limit = int(self.approval_cfg.get("thread_list_limit", 50))
        params = {
            "archived": False,
            "limit": limit,
            "sortKey": "updated_at",
            "sortDirection": "desc",
        }
        source_kinds = self.approval_cfg.get("thread_source_kinds")
        if isinstance(source_kinds, list):
            cleaned = [item for item in source_kinds if isinstance(item, str) and item]
            if cleaned:
                params["sourceKinds"] = cleaned
        response = self.call(
            "thread/list",
            params,
            timeout=self.timeout,
        )
        threads = response.get("data") if isinstance(response.get("data"), list) else []
        waiting_threads: set[str] = set()
        seen_threads: set[str] = set()

        for raw_thread in threads:
            if not isinstance(raw_thread, dict):
                continue
            thread_id = raw_thread.get("id")
            if not isinstance(thread_id, str):
                continue
            seen_threads.add(thread_id)
            self.thread_metadata[thread_id] = raw_thread
            if is_waiting_on_approval(raw_thread):
                waiting_threads.add(thread_id)

        for thread_id in seen_threads - waiting_threads:
            self.resumed_threads.discard(thread_id)
            self.drop_pending_for_thread(thread_id)

        for thread_id in waiting_threads:
            if thread_id in self.resumed_threads:
                continue
            self.send_request(
                "thread/resume",
                {
                    "threadId": thread_id,
                    "excludeTurns": True,
                    "approvalsReviewer": "user",
                    "persistExtendedHistory": False,
                }
            )
            self.resumed_threads.add(thread_id)

        self.scan_rollout_fallback()
        self.last_error = None
        self.write_state()

    def consume_decisions(self) -> None:
        path = self.decisions_path
        if not path.exists():
            return
        size = path.stat().st_size
        if size < self.decision_offset:
            self.decision_offset = 0
        with path.open("r", encoding="utf-8") as f:
            f.seek(self.decision_offset)
            lines = f.readlines()
            self.decision_offset = f.tell()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                decision = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(decision, dict):
                self.apply_decision(decision)

    def apply_decision(self, decision: Dict[str, Any]) -> None:
        approval_id = decision.get("approval_id") or decision.get("id")
        choice = decision.get("decision")
        if not isinstance(approval_id, str) or not isinstance(choice, str):
            return
        approval = self.pending.get(approval_id)
        if not approval:
            return
        try:
            result = decision_response_for(approval, choice)
            self.send({"id": approval.get("server_request_id"), "result": result})
        except Exception as exc:
            self.last_error = str(exc)
            self.write_state()
            return
        self.pending.pop(approval_id, None)
        self.last_error = None
        self.write_state()

    def write_state(self) -> None:
        combined = dict(self.scanned_pending)
        combined.update(self.pending)
        approvals = sorted(combined.values(), key=lambda item: item.get("created_at", ""))
        payload: Dict[str, Any] = {
            "version": 1,
            "updated_at": utc_now_iso(),
            "pending_count": len(approvals),
            "approvals": approvals,
            "notify": bool(self.approval_cfg.get("notify", True)),
            "pulse": bool(self.approval_cfg.get("pulse", True)),
            "watcher": {
                "status": "error" if self.last_error else "ok",
                "source": self.source,
                "transport": self.transport,
                "direct_pending_count": len(self.pending),
                "rollout_scan_pending_count": len(self.scanned_pending),
            },
        }
        if self.last_error:
            payload["error"] = {"message": self.last_error, "updated_at": utc_now_iso()}
        if self.last_scan_error:
            payload["scan_error"] = {"message": self.last_scan_error, "updated_at": utc_now_iso()}
        write_json(self.state_path, payload)

    def run_forever(self) -> None:
        next_thread_poll = 0.0
        next_decision_poll = 0.0
        while True:
            now = time.monotonic()
            if now >= next_thread_poll:
                self.poll_threads()
                next_thread_poll = now + self.poll_interval
            if now >= next_decision_poll:
                self.consume_decisions()
                next_decision_poll = now + self.decision_poll_interval
            timeout = min(max(next_thread_poll - now, 0.05), max(next_decision_poll - now, 0.05), 0.2)
            message = self.read_message(timeout)
            if message:
                self.handle_message(message)


def run_with_reconnect(cfg: Dict[str, Any], state_path: Path, decisions_path: Path) -> None:
    approval_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    reconnect_delay = float(approval_cfg.get("reconnect_delay_seconds", 5.0))
    while True:
        watcher = AppServerApprovalWatcher(cfg, state_path, decisions_path)
        try:
            watcher.start()
            watcher.write_state()
            watcher.run_forever()
        except KeyboardInterrupt:
            watcher.stop()
            raise
        except Exception as exc:
            watcher.last_error = str(exc)
            watcher.write_state()
            watcher.stop()
            time.sleep(reconnect_delay)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Watch Codex app-server for pending approval requests.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to Easy Codex Limit Check config JSON.")
    parser.add_argument("--state-path", default=DEFAULT_APPROVAL_STATE_PATH, help="Approval state JSON path.")
    parser.add_argument("--decisions-path", default=DEFAULT_APPROVAL_DECISIONS_PATH, help="Approval decision JSONL path.")
    parser.add_argument("--dry-run", action="store_true", help="Write one empty state snapshot and exit.")
    args = parser.parse_args(argv)

    config_path = Path(os.path.expanduser(args.config)).resolve()
    state_path = Path(os.path.expanduser(args.state_path)).resolve()
    decisions_path = Path(os.path.expanduser(args.decisions_path)).resolve()
    cfg = parse_config(config_path)

    approvals_cfg = cfg.get("approvals") if isinstance(cfg.get("approvals"), dict) else {}
    if approvals_cfg.get("enabled") is False:
        write_json(
            state_path,
            {
                "version": 1,
                "updated_at": utc_now_iso(),
                "pending_count": 0,
                "approvals": [],
                "watcher": {"status": "disabled", "source": "config"},
            },
        )
        return 0

    if args.dry_run:
        watcher = AppServerApprovalWatcher(cfg, state_path, decisions_path)
        watcher.write_state()
        print(json.dumps({"status": "ok", "state_path": str(state_path)}, ensure_ascii=False))
        return 0

    try:
        run_with_reconnect(cfg, state_path, decisions_path)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
