"""Validate the raw AndroidJUnitRunner result for the exact selected test set."""
from collections import Counter
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
inventory = dict.fromkeys(cases)
expected = len(inventory)


def values(key):
    return re.findall(rf"^{key}(.+)$", output, re.M)


records = re.split(r"^INSTRUMENTATION_STATUS_CODE: (.*)$", output, flags=re.M)
events = [(code, dict(re.findall(r"^INSTRUMENTATION_STATUS: (\w+)=(.*)$", bundle, re.M)))
          for bundle, code in zip(records[::2], records[1::2])]
by_test = {name: [] for name in inventory}
errors = []
if not expected or expected != len(cases):
    errors.append("Expected test inventory is empty or contains duplicate names")

for index, (code, fields) in enumerate(events, start=1):
    name = fields.get("test")
    if fields.get("class") != test_class or name not in by_test:
        errors.append(f"Unexpected test identity at event {index}")
        continue
    if fields.get("numtests") != str(expected):
        errors.append(f"`{name}` declared an unexpected test count at event {index}")
    by_test[name].append(code)

terminal_outcomes = {"0": "passed", "-1": "failed", "-2": "failed",
                     "-3": "skipped", "-4": "skipped"}
started = 0
outcomes = Counter()
for name, codes in by_test.items():
    starts = codes.count("1")
    terminals = [code for code in codes if code in terminal_outcomes]
    started += starts > 0
    if starts > 1:
        errors.append(f"`{name}` has duplicate start events ({starts})")
    if len(terminals) > 1:
        errors.append(f"`{name}` has duplicate terminal events ({len(terminals)})")
    if not starts and codes != ["-3"]:
        errors.append(f"`{name}` is missing its start event")
    if not terminals:
        errors.append(f"`{name}` is missing its terminal event")
    if codes == ["-3"] or (len(codes) == 2 and codes[0] == "1" and codes[1] in terminal_outcomes):
        outcomes[terminal_outcomes[codes[-1]]] += 1
    elif (starts == 1 and len(terminals) == 1) or len(codes) != starts + len(terminals):
        errors.append(f"`{name}` has an invalid event sequence")

# Preserve the runner's contract that each start is immediately followed by
# that same test's successful terminal status in a passing run.
paired = all(start_code == "1" and end_code == "0" and start.get("test") == end.get("test")
             for (start_code, start), (end_code, end) in zip(events[::2], events[1::2]))
if outcomes["passed"] == expected and not paired:
    errors.append("Successful test events are out of order")
valid = (
    exit_code == "0"
    and not errors
    and len(events) == 2 * expected
    and paired
    and outcomes["passed"] == expected
    and values("INSTRUMENTATION_CODE: ") == ["-1"]
    and re.search(rf"^OK \({expected} tests?\)$", output, re.M)
    and not re.search(r"^INSTRUMENTATION_(?:FAILED|ABORTED|RESULT: (?:shortMsg|longMsg)=)", output, re.M)
)
test_label = test_class if case.startswith("@") else f"{test_class}#{case}"
print(f"| {scenario} | {test_label} | {started}/{expected} | {outcomes['passed']} | "
      f"{outcomes['failed']} | {outcomes['skipped']} | {len(events)} | "
      f"{elapsed}s | {'PASS' if valid else 'FAIL'} (exit {exit_code}) |")
if not valid:
    for error in errors:
        print(f"- Instrumentation protocol error: {error}")
    for name, codes in by_test.items():
        for code in dict.fromkeys(codes):
            if terminal_outcomes.get(code) in {"failed", "skipped"}:
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
