"""Validate the raw AndroidJUnitRunner result for exactly one selected test."""
import re
import sys
from pathlib import Path


path, test_class, case, scenario, elapsed, exit_code = sys.argv[1:]
output = Path(path).read_text(errors="replace")


def values(key):
    return re.findall(rf"^{key}(.+)$", output, re.M)


codes = values("INSTRUMENTATION_STATUS_CODE: ")
started = codes.count("1")
passed = codes.count("0")
failed = codes.count("-1") + codes.count("-2")
skipped = codes.count("-3") + codes.count("-4")
valid = (
    exit_code == "0"
    and codes == ["1", "0"]
    and values("INSTRUMENTATION_STATUS: class=") == [test_class] * 2
    and values("INSTRUMENTATION_STATUS: test=") == [case] * 2
    and values("INSTRUMENTATION_STATUS: numtests=") == ["1", "1"]
    and values("INSTRUMENTATION_CODE: ") == ["-1"]
    and re.search(r"^OK \(1 test\)$", output, re.M)
    and not re.search(r"^INSTRUMENTATION_(?:FAILED|ABORTED|RESULT: (?:shortMsg|longMsg)=)", output, re.M)
)
print(f"| {scenario} | {test_class}#{case} | {started}/1 | {passed} | {failed} | {skipped} | "
      f"{elapsed}s | {'PASS' if valid else 'FAIL'} (exit {exit_code}) |")
if not valid:
    for line in output.splitlines():
        match = re.search(
            r"(?:Private route condition not reached \([a-zA-Z0-9= ]+\)"
            r"|java\.lang\.AssertionError: expected:<\d+> but was:<\d+>"
            r"|com\.littlebuddy\.[A-Za-z0-9_$]+\.[A-Za-z0-9_$]+\([A-Za-z0-9_.]+:\d+\))",
            line,
        )
        if match:
            print(f"- `{match.group()}`")
sys.exit(0 if valid else 1)
