import io
import json
import os
import unittest
from datetime import date, datetime, timezone
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
        body = io.BytesIO(json.dumps({"aws": last}).encode())
        with mock.patch.object(handler.s3, "get_object", return_value={"Body": body}), \
             mock.patch.object(handler.ce, "get_cost_and_usage", return_value={"ResultsByTime": [month("2026-11-01", 1)]}) as ce:
            return handler.aws_cost(self.now), ce

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


if __name__ == "__main__":
    unittest.main()
