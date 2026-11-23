"""Regression tests for AndroidJUnitRunner result accounting."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PARSER = Path(__file__).with_name("android-ci-result.py")
TEST_CLASS = "com.littlebuddy.AnimalActivityTest"


class InstrumentationResultTest(unittest.TestCase):
    def check_result(self, events, counts, *diagnostics, success=False):
        with tempfile.TemporaryDirectory() as scratch:
            inventory = Path(scratch) / "Suite.kt"
            inventory.write_text("@Test fun alpha() {}\n@Test fun beta() {}\n")
            result = Path(scratch) / "instrumentation"
            result.write_text("".join(
                f"INSTRUMENTATION_STATUS: class={TEST_CLASS}\n"
                f"INSTRUMENTATION_STATUS: test={name}\n"
                "INSTRUMENTATION_STATUS: numtests=2\n"
                f"INSTRUMENTATION_STATUS_CODE: {code}\n"
                for name, code in events
            ) + "OK (2 tests)\nINSTRUMENTATION_CODE: -1\n")
            completed = subprocess.run(
                [sys.executable, str(PARSER), str(result), TEST_CLASS, f"@{inventory}",
                 "normal", "3", "0"], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0 if success else 1, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines()[0].split(" | ")[2:7],
            [*counts, str(len(events))],
        )
        for message in diagnostics:
            self.assertIn(message, completed.stdout)

    def test_complete_suite_passes(self):
        self.check_result(
            [("alpha", 1), ("alpha", 0), ("beta", 1), ("beta", 0)],
            ["2/2", "2", "0", "0"], success=True,
        )

    def test_duplicate_start_cannot_inflate_started_or_confirm_pass(self):
        self.check_result(
            [("alpha", 1), ("alpha", 1), ("alpha", 0), ("beta", 1), ("beta", 0)],
            ["2/2", "1", "0", "0"], "`alpha` has duplicate start events",
        )

    def test_duplicate_terminal_cannot_inflate_passes(self):
        self.check_result(
            [("alpha", 1), ("alpha", 0), ("alpha", 0), ("beta", 1), ("beta", 0)],
            ["2/2", "1", "0", "0"], "`alpha` has duplicate terminal events",
        )

    def test_full_duplicate_cannot_hide_missing_test(self):
        self.check_result(
            [("alpha", 1), ("alpha", 0), ("alpha", 1), ("alpha", 0)],
            ["1/2", "0", "0", "0"], "`alpha` has duplicate start events",
            "`alpha` has duplicate terminal events", "`beta` is missing its start event",
            "`beta` is missing its terminal event",
        )

    def test_unexpected_test_does_not_count(self):
        self.check_result(
            [("alpha", 1), ("alpha", 0), ("beta", 1), ("beta", 0), ("extra", 1), ("extra", 0)],
            ["2/2", "2", "0", "0"], "Unexpected test identity at event 5",
        )

    def test_unpaired_start_and_terminal_do_not_count_as_passes(self):
        self.check_result(
            [("alpha", 1), ("beta", 0)],
            ["1/2", "0", "0", "0"], "`alpha` is missing its terminal event",
            "`beta` is missing its start event",
        )

    def test_failure_and_ignored_are_counted_once(self):
        self.check_result(
            [("alpha", 1), ("alpha", -2), ("beta", -3)],
            ["1/2", "0", "1", "1"],
        )

    def test_nonadjacent_pairs_fail(self):
        self.check_result(
            [("alpha", 1), ("beta", 1), ("alpha", 0), ("beta", 0)],
            ["2/2", "2", "0", "0"], "Successful test events are out of order",
        )


if __name__ == "__main__":
    unittest.main()
