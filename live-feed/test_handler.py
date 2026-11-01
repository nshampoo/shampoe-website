import json
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("BUCKET", "test-bucket")
import handler  # noqa: E402


def month(start, amount):
    return {"TimePeriod": {"Start": start}, "Total": {"UnblendedCost": {"Amount": str(amount)}}}


class SummarizeCost(unittest.TestCase):
    def test_month_is_last_period_and_total_is_sum(self):
        out = handler.summarize_cost([month("2026-09-01", "0.0000001"), month("2026-10-01", 2.504), month("2026-11-01", 0.31)], date(2026, 11, 1))
        self.assertEqual(out, {"as_of": "2026-11-01", "month": 0.31, "total": 2.81, "since": "2026-10"})

    def test_no_spend(self):
        out = handler.summarize_cost([month("2026-11-01", 0)], date(2026, 11, 1))
        self.assertEqual((out["month"], out["total"], out["since"]), (0, 0, None))


class AwsCostCache(unittest.TestCase):
    now = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)

    def run_with_last(self, last):
        with mock.patch.object(handler.ce, "get_cost_and_usage", return_value={"ResultsByTime": [month("2026-11-01", 1)]}) as ce:
            return handler.aws_cost(self.now, {"aws": last}), ce

    def test_reuses_todays_result_without_calling_cost_explorer(self):
        last = {"as_of": "2026-11-01", "month": 9, "total": 9, "since": "2026-09"}
        out, ce = self.run_with_last(last)
        self.assertEqual(out, last)
        ce.assert_not_called()

    def test_calls_once_when_cached_result_is_stale(self):
        out, ce = self.run_with_last({"as_of": "2026-10-31", "month": 9, "total": 9})
        self.assertEqual(out["as_of"], "2026-11-01")
        ce.assert_called_once()
        period = ce.call_args.kwargs["TimePeriod"]
        self.assertEqual(period, {"Start": "2025-11-01", "End": "2026-11-02"})


class Health(unittest.TestCase):
    t0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    def step(self, prev, errors, minutes):
        return handler.health(prev, errors, self.t0 + timedelta(minutes=minutes))

    def test_first_run_starts_every_source(self):
        out, alerts = self.step({}, {"strava": "boom"}, 0)
        self.assertEqual(set(out), set(handler.LABELS))
        self.assertEqual(out["github"], {"ok": True, "since": "2026-11-01T12:00:00+00:00"})
        self.assertFalse(out["strava"]["ok"])
        self.assertEqual(alerts, [])

    def test_since_holds_while_state_is_unchanged(self):
        out, _ = self.step({}, {}, 0)
        out, _ = self.step(out, {}, 15)
        self.assertEqual(out["github"]["since"], "2026-11-01T12:00:00+00:00")

    def test_emails_once_after_two_hours_down_then_on_recovery(self):
        out, alerts = self.step({}, {"strava": "HTTP 500"}, 0)
        out, alerts = self.step(out, {"strava": "HTTP 500"}, 105)
        self.assertEqual(alerts, [])
        out, alerts = self.step(out, {"strava": "HTTP 500"}, 120)
        self.assertEqual([s for s, _ in alerts], ["shampoe.com: Strava is down"])
        self.assertIn("HTTP 500", alerts[0][1])
        out, alerts = self.step(out, {"strava": "HTTP 500"}, 135)
        self.assertEqual(alerts, [])
        out, alerts = self.step(out, {}, 150)
        self.assertEqual([s for s, _ in alerts], ["shampoe.com: Strava is working again"])
        self.assertEqual(out["strava"], {"ok": True, "since": "2026-11-01T14:30:00+00:00"})

    def test_short_outage_stays_quiet(self):
        out, _ = self.step({}, {"volo": "timeout"}, 0)
        out, alerts = self.step(out, {}, 30)
        self.assertEqual(alerts, [])

    def test_error_text_stays_out_of_public_state(self):
        out, _ = self.step({}, {"strava": "token=abc123"}, 0)
        self.assertNotIn("abc123", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
