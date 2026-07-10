from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import watch_approvals  # noqa: E402


class ApprovalNormalizationTests(unittest.TestCase):
    def test_app_server_command_uses_chatgpt_bundle_when_path_lookup_fails(self) -> None:
        bundled_codex = "/Applications/ChatGPT.app/Contents/Resources/codex"

        with patch.object(watch_approvals.shutil, "which", return_value=None):
            with patch.object(watch_approvals.os.path, "exists", side_effect=lambda path: path == bundled_codex):
                command = watch_approvals.app_server_command({"app_server": {"command": "codex"}})

        self.assertEqual(command, [bundled_codex, "app-server", "--listen", "stdio://"])

    def test_modern_command_approval_normalizes_display_fields(self) -> None:
        approval = watch_approvals.normalize_approval_request(
            watch_approvals.MODERN_COMMAND,
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "approvalId": None,
                "command": "git push origin main",
                "cwd": "/tmp/project",
                "reason": "Need network access",
            },
            99,
            {"id": "thread-1", "preview": "Ship the feature"},
        )

        self.assertEqual(approval["kind"], "command")
        self.assertEqual(approval["summary"], "git push origin main")
        self.assertEqual(approval["thread_title"], "Ship the feature")
        self.assertEqual(approval["cwd"], "/tmp/project")
        self.assertTrue(approval["supports_direct_decision"])
        self.assertEqual(approval["decisions"][0]["id"], "accept")

    def test_legacy_exec_decision_maps_to_legacy_response(self) -> None:
        approval = watch_approvals.normalize_approval_request(
            watch_approvals.LEGACY_EXEC,
            {
                "conversationId": "thread-1",
                "callId": "call-1",
                "command": ["git", "push"],
                "cwd": "/tmp/project",
                "parsedCmd": [],
            },
            "request-1",
            {},
        )

        self.assertEqual(approval["command"], "git push")
        self.assertEqual(watch_approvals.decision_response_for(approval, "accept"), {"decision": "approved"})
        self.assertEqual(
            watch_approvals.decision_response_for(approval, "acceptForSession"),
            {"decision": "approved_for_session"},
        )
        self.assertEqual(watch_approvals.decision_response_for(approval, "cancel"), {"decision": "abort"})

    def test_file_change_approval_has_deterministic_id(self) -> None:
        params = {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item-1",
            "grantRoot": "/tmp/project",
        }

        first = watch_approvals.normalize_approval_request(watch_approvals.MODERN_FILE_CHANGE, params, 10, {})
        second = watch_approvals.normalize_approval_request(watch_approvals.MODERN_FILE_CHANGE, params, 10, {})

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["kind"], "fileChange")
        self.assertIn("Write access", first["detail"])

    def test_permissions_decision_grants_requested_permissions(self) -> None:
        approval = watch_approvals.normalize_approval_request(
            watch_approvals.MODERN_PERMISSIONS,
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "cwd": "/tmp/project",
                "permissions": {"network": {"enabled": True}},
            },
            11,
            {},
        )

        self.assertEqual(approval["kind"], "permissions")
        self.assertEqual(
            watch_approvals.decision_response_for(approval, "grantSession"),
            {"permissions": {"network": {"enabled": True}}, "scope": "session"},
        )
        self.assertEqual(
            watch_approvals.decision_response_for(approval, "decline"),
            {"permissions": {}, "scope": "turn"},
        )

    def test_active_flags_detect_waiting_on_approval(self) -> None:
        self.assertTrue(
            watch_approvals.is_waiting_on_approval(
                {"status": {"type": "active", "activeFlags": ["waitingOnApproval"]}}
            )
        )
        self.assertFalse(watch_approvals.is_waiting_on_approval({"status": {"type": "idle"}}))

    def test_apply_decision_sends_json_rpc_response_and_removes_pending(self) -> None:
        class FakeWatcher(watch_approvals.AppServerApprovalWatcher):
            def __init__(self) -> None:
                super().__init__({}, Path("/tmp/approval_state.json"), Path("/tmp/approval_decisions.jsonl"))
                self.sent: list[dict] = []

            def send(self, payload: dict) -> None:
                self.sent.append(payload)

            def write_state(self) -> None:
                return None

        approval = watch_approvals.normalize_approval_request(
            watch_approvals.MODERN_COMMAND,
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "command": "pwd",
            },
            42,
            {},
        )
        watcher = FakeWatcher()
        watcher.pending[approval["id"]] = approval

        watcher.apply_decision({"approval_id": approval["id"], "decision": "accept"})

        self.assertEqual(watcher.sent, [{"id": 42, "result": {"decision": "accept"}}])
        self.assertEqual(watcher.pending, {})

    def test_v2_status_changed_notification_drops_pending(self) -> None:
        class FakeWatcher(watch_approvals.AppServerApprovalWatcher):
            def __init__(self) -> None:
                super().__init__({}, Path("/tmp/approval_state.json"), Path("/tmp/approval_decisions.jsonl"))

            def write_state(self) -> None:
                return None

        approval = watch_approvals.normalize_approval_request(
            watch_approvals.MODERN_COMMAND,
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "command": "pwd",
            },
            42,
            {},
        )
        watcher = FakeWatcher()
        watcher.pending[approval["id"]] = approval

        watcher.handle_notification(
            "thread/status/changed",
            {"threadId": "thread-1", "status": {"type": "idle"}},
        )

        self.assertEqual(watcher.pending, {})


class RolloutScanTests(unittest.TestCase):
    def write_state_db(self, root: Path, rollout_path: Path) -> None:
        db = root / "state_5.sqlite"
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                """
                create table threads (
                    id text primary key,
                    title text not null,
                    cwd text not null,
                    rollout_path text not null,
                    updated_at integer not null,
                    archived integer not null
                )
                """
            )
            conn.execute(
                "insert into threads values (?, ?, ?, ?, ?, ?)",
                ("thread-1", "Needs approval", "/tmp/project", str(rollout_path), int(datetime.now(timezone.utc).timestamp()), 0),
            )
            conn.commit()
        finally:
            conn.close()

    def test_rollout_scan_detects_unanswered_escalated_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "rollout.jsonl"
            call = {
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": json.dumps(
                        {
                            "cmd": "git push origin branch",
                            "sandbox_permissions": "require_escalated",
                            "justification": "Need network access",
                        }
                    ),
                },
            }
            rollout.write_text(json.dumps(call) + "\n", encoding="utf-8")
            self.write_state_db(root, rollout)

            approvals = watch_approvals.scan_rollout_pending_approvals(
                {"approvals": {"codex_home": str(root), "rollout_scan_recent_seconds": 3600}}
            )

        self.assertEqual(len(approvals), 1)
        approval = next(iter(approvals.values()))
        self.assertEqual(approval["method"], watch_approvals.ROLLOUT_PENDING_TOOL)
        self.assertFalse(approval["supports_direct_decision"])
        self.assertIn("git push", approval["summary"])

    def test_rollout_scan_ignores_calls_with_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollout = root / "rollout.jsonl"
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            call = {
                "timestamp": timestamp,
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": json.dumps({"cmd": "git push", "sandbox_permissions": "require_escalated"}),
                },
            }
            output = {
                "timestamp": timestamp,
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-1", "output": "done"},
            }
            rollout.write_text(json.dumps(call) + "\n" + json.dumps(output) + "\n", encoding="utf-8")
            self.write_state_db(root, rollout)

            approvals = watch_approvals.scan_rollout_pending_approvals(
                {"approvals": {"codex_home": str(root), "rollout_scan_recent_seconds": 3600}}
            )

        self.assertEqual(approvals, {})


if __name__ == "__main__":
    unittest.main()
