import subprocess
import unittest
from unittest.mock import call, patch

from tools.push_snapshot import push_snapshot


class PushSnapshotTests(unittest.TestCase):
    @patch("tools.push_snapshot.time.sleep")
    @patch("tools.push_snapshot.subprocess.run")
    def test_success_does_not_retry(self, run, sleep):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")

        self.assertEqual(push_snapshot(), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["git", "push", "origin", "HEAD:main"])
        sleep.assert_not_called()

    @patch("tools.push_snapshot.time.sleep")
    @patch("tools.push_snapshot.subprocess.run")
    def test_commit_refs_rules_error_retries_then_succeeds(self, run, sleep):
        failure = subprocess.CompletedProcess(
            [], 1, "", "remote: fatal error in commit_refs_rules\n"
        )
        run.side_effect = [failure, failure, subprocess.CompletedProcess([], 0, "", "")]

        self.assertEqual(push_snapshot(), 0)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(10), call(30)])

    @patch("tools.push_snapshot.time.sleep")
    @patch("tools.push_snapshot.subprocess.run")
    def test_permanent_errors_are_not_retried(self, run, sleep):
        for error in (
            "remote: Permission denied.\n",
            "! [rejected] HEAD -> main (non-fast-forward)\n",
            "remote: GH013: Repository rule violations found.\n",
        ):
            with self.subTest(error=error):
                run.reset_mock()
                run.return_value = subprocess.CompletedProcess([], 1, "", error)

                self.assertEqual(push_snapshot(), 1)
                run.assert_called_once()
                sleep.assert_not_called()

    @patch("tools.push_snapshot.time.sleep")
    @patch("tools.push_snapshot.subprocess.run")
    def test_transient_failure_stops_after_three_attempts(self, run, sleep):
        run.return_value = subprocess.CompletedProcess(
            [], 1, "", "fatal: the requested URL returned error: 503\n"
        )

        self.assertEqual(push_snapshot(), 1)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(10), call(30)])

    @patch("tools.push_snapshot.time.sleep")
    @patch("tools.push_snapshot.subprocess.run")
    def test_timeout_can_recover(self, run, sleep):
        run.side_effect = [
            subprocess.TimeoutExpired(["git", "push"], 120),
            subprocess.CompletedProcess([], 0, "", "Everything up-to-date\n"),
        ]

        self.assertEqual(push_snapshot(), 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()
