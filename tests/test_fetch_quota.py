from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_quota  # noqa: E402


def base_cfg() -> dict:
    return fetch_quota.parse_config(None)


class AppServerProviderTests(unittest.TestCase):
    def test_rate_limits_by_limit_id_maps_main_and_additional_buckets(self) -> None:
        payload = {
            "rateLimits": {
                "limitId": "codex",
                "limitName": "Codex",
                "planType": "pro",
                "primary": {"usedPercent": 25, "resetsAt": 1770000000, "windowDurationMins": 300},
                "secondary": {"usedPercent": 5, "resetsAt": 1770500000, "windowDurationMins": 10080},
                "credits": {"hasCredits": True, "unlimited": False, "balance": "10"},
            },
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "limitName": "Codex",
                    "primary": {"usedPercent": 25, "resetsAt": 1770000000, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 5, "resetsAt": 1770500000, "windowDurationMins": 10080},
                },
                "codex_bengalfox": {
                    "limitId": "codex_bengalfox",
                    "limitName": "GPT-5.3-Codex-Spark",
                    "primary": {"usedPercent": 11, "resetsAt": 1770100000, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 6, "resetsAt": 1770600000, "windowDurationMins": 10080},
                },
            },
        }

        with patch.object(fetch_quota, "fetch_app_server_rate_limits", return_value=payload):
            state = fetch_quota.resolve_app_server_state(base_cfg(), {})

        self.assertEqual(state["source"]["provider"], "app_server")
        self.assertEqual(state["rate_limits"][0]["name"], "Rate limits remaining")
        self.assertEqual(state["rate_limits"][0]["five_h"]["remaining_percent"], 75.0)
        self.assertEqual(state["rate_limits"][0]["week"]["remaining_percent"], 95.0)
        self.assertEqual(state["rate_limits"][1]["name"], "GPT-5.3-Codex-Spark")
        self.assertEqual(state["rate_limits"][1]["five_h"]["remaining_percent"], 89.0)
        self.assertEqual(state["credits"]["has_credits"], True)

    def test_single_bucket_rate_limits_is_supported(self) -> None:
        payload = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 30, "resetsAt": 1770000000, "windowDurationMins": 300},
                "secondary": {"usedPercent": 4, "resetsAt": 1770500000, "windowDurationMins": 10080},
            }
        }

        with patch.object(fetch_quota, "fetch_app_server_rate_limits", return_value=payload):
            state = fetch_quota.resolve_app_server_state(base_cfg(), {})

        self.assertEqual(len(state["rate_limits"]), 1)
        self.assertEqual(state["five_h"]["remaining"], 70.0)
        self.assertEqual(state["week"]["remaining"], 96.0)

    def test_missing_secondary_keeps_usable_primary_bucket(self) -> None:
        payload = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {"usedPercent": 31, "resetsAt": 1770000000, "windowDurationMins": 300},
                "secondary": None,
            }
        }

        with patch.object(fetch_quota, "fetch_app_server_rate_limits", return_value=payload):
            state = fetch_quota.resolve_app_server_state(base_cfg(), {})

        self.assertEqual(state["rate_limits"][0]["five_h"]["remaining_percent"], 69.0)
        self.assertIsNone(state["rate_limits"][0]["week"]["remaining_percent"])

    def test_app_server_failure_can_fallback_to_wham(self) -> None:
        fallback_state = {
            "source": {
                "provider": "codex_wham",
                "refreshed": {},
            },
            "five_h": {"remaining": 70},
            "week": {"remaining": 95},
            "rate_limits": [],
        }

        with patch.object(fetch_quota, "resolve_app_server_state", side_effect=RuntimeError("boom")):
            with patch.object(fetch_quota, "resolve_codex_state", return_value=fallback_state):
                state = fetch_quota.resolve_state(base_cfg(), {})

        self.assertEqual(state["source"]["provider"], "codex_wham")
        self.assertEqual(state["source"]["refreshed"]["fallback_from"], "app_server")
        self.assertIn("boom", state["source"]["refreshed"]["fallback_error"])


if __name__ == "__main__":
    unittest.main()
