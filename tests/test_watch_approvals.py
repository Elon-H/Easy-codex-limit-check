from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import watch_approvals  # noqa: E402


class ApprovalNormalizationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
