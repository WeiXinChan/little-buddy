"""Validate the raw AndroidJUnitRunner result for the exact selected test set."""
import re
import sys
from pathlib import Path


path, test_class, case, scenario, elapsed, exit_code = sys.argv[1:]
output = Path(path).read_text(errors="replace")
# Class selection runs the entire suite. Read its expected inventory from the
# checked-out test source so omissions are visible even if JUnit reports OK.
cases = (
    re.findall(r"@Test\s+fun\s+(\w+)\s*\(", Path(case[1:]).read_text())
    if case.startswith("@") else [case]
)
expected = len(cases)


def values(key):
    return re.findall(rf"^{key}(.+)$", output, re.M)


records = re.split(r"^INSTRUMENTATION_STATUS_CODE: (-?\d+)\n", output, flags=re.M)
events = [(code, dict(re.findall(r"^INSTRUMENTATION_STATUS: (\w+)=(.*)$", bundle, re.M)))
          for bundle, code in zip(records[::2], records[1::2])]
codes = [code for code, _ in events]
started = codes.count("1")
passed = codes.count("0")
failed = codes.count("-1") + codes.count("-2")
skipped = codes.count("-3") + codes.count("-4")
valid = (
    exit_code == "0"
    and expected > 0
    and len(events) == 2 * expected
    and codes == ["1", "0"] * expected
    and all(start.get("test") == end.get("test")
            for (_, start), (_, end) in zip(events[::2], events[1::2]))
    and sorted(fields.get("test", "") for _, fields in events) == sorted(cases * 2)
    and all(fields.get("class") == test_class and fields.get("numtests") == str(expected)
            for _, fields in events)
    and values("INSTRUMENTATION_CODE: ") == ["-1"]
    and re.search(rf"^OK \({expected} tests?\)$", output, re.M)
    and not re.search(r"^INSTRUMENTATION_(?:FAILED|ABORTED|RESULT: (?:shortMsg|longMsg)=)", output, re.M)
)
test_label = test_class if case.startswith("@") else f"{test_class}#{case}"
print(f"| {scenario} | {test_label} | {started}/{expected} | {passed} | {failed} | {skipped} | "
      f"{elapsed}s | {'PASS' if valid else 'FAIL'} (exit {exit_code}) |")
if not valid:
    for code, fields in events:
        name = fields.get("test", "")
        if code not in {"1", "0"} and re.fullmatch(r"\w+", name):
            print(f"- `{name}` reported instrumentation status {code}")
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
