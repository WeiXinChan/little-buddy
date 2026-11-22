"""Exercise actual subprocess orchestration with local ADB and SSH stand-ins."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

import run

FAKE = r"""
import json, os, pathlib, shlex, sys, time
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
mode = os.environ["FAKE_MODE"]
args = sys.argv[1:]
name = Path(sys.argv[0]).name

def record(text):
    with (state / "events").open("a") as out:
        print(text, file=out)

if name == "ssh":
    if "-M" in args:
        record("master")
        if mode == "password":
            sys.exit(255)
        (state / "master").touch()
        time.sleep(120)
    elif "-O" in args:
        sys.exit(0 if (state / "master").exists() else 1)
    else:
        command = shlex.split(args[-1])
        assert command[:2] == ["bash", "-c"]
        assert command[3] == "fixture-session"
        assert command[4] == os.environ["FAKE_CHECKOUT"]
        _, case, run_id = command[-3:]
        unit = f"little-buddy-regression-{run_id}-{case}.service"
        record("fixture " + case)
        print("READY " + unit, flush=True)
        if mode == "disconnect":
            sys.exit(255)
        assert sys.stdin.readline() in ("STOP\n", "")
        record("stop " + case)
        print("STOPPED " + unit)
    sys.exit()

if args == ["devices"]:
    rows = {"none": "", "multi": "one device\ntwo device",
            "unauthorized": "secret-device unauthorized"}
    print("List of devices attached")
    print(rows.get(mode, "secret-device device"))
    sys.exit()
assert args[:2] == ["-s", "secret-device"]
args = args[2:]
mapping = state / "reverse"
if args == ["get-devpath"]:
    print("usb:1-1")
elif args == ["reverse", "--list"]:
    if mapping.exists() or mode == "reverse":
        print("UsbFfs tcp:9444 tcp:9444")
elif args == ["reverse", "--no-rebind", "tcp:9444", "tcp:9444"]:
    mapping.touch(exist_ok=False)
    record("reverse")
elif args == ["reverse", "--remove", "tcp:9444"]:
    mapping.unlink()
    record("remove")
elif args[:3] == ["shell", "pm", "path"]:
    print("package:/data/app/" + args[3] + "/base.apk")
elif args[:2] == ["shell", "sha256sum"]:
    manifest = json.loads(Path(os.environ["FAKE_MANIFEST"]).read_text())
    print(list(manifest["apk"].values())[int(".sim.test/" in args[2])], args[2])
elif args[:4] == ["shell", "pm", "list", "instrumentation"]:
    print("instrumentation:com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner (target=com.littlebuddy.sim)")
elif args[:3] == ["shell", "cat", "/proc/uptime"]:
    print("1.00 2.00")
elif args[:2] == ["shell", "logcat"]:
    print("transcript secret")
    print("event=segment_ack op=1 segment=1 ms=2000")
elif args[:3] == ["shell", "am", "force-stop"]:
    record("force-stop")
elif args[:3] == ["shell", "am", "instrument"]:
    assert "-r" in args and "-w" in args
    case = args[args.index("animalScenario") + 1]
    record("instrument " + case)
    if mode in ("timeout", "signal"):
        time.sleep(120)
    print("private stack message: secret-device")
    for code in (1, {"fail": -2, "skip": -4}.get(mode, 0)):
        print("INSTRUMENTATION_STATUS: class=com.littlebuddy.AnimalPrivateActivityTest")
        print("INSTRUMENTATION_STATUS: test=stopOrDisconnectClearsAndAllowsOnlyAManualNewGame")
        print("INSTRUMENTATION_STATUS: numtests=1")
        print("INSTRUMENTATION_STATUS_CODE:", code)
    print("OK (1 test)")
    print("INSTRUMENTATION_CODE:", 0 if mode == "crash" else -1)
else:
    sys.exit("Unexpected adb command")
"""


class Orchestration(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="lb test ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for tool in ("ssh", "adb"):
            path = self.root / tool
            path.write_text("#!" + sys.executable + "\n" + FAKE)
            path.chmod(0o700)

    def exercise(self, mode, *arguments, interrupt=None):
        checkout = "/remote/path with spaces/'quote'; $(literal)"
        environment = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                           FAKE_STATE=str(self.root), FAKE_MODE=mode, FAKE_CHECKOUT=checkout,
                           FAKE_MANIFEST=str(run.HERE / "manifest.json"))
        events_file = self.root / "events"
        with subprocess.Popen([sys.executable, str(run.HERE / "run.py"), "--checkout", checkout,
                               *arguments], env=environment, cwd=self.root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            if interrupt:
                end = time.monotonic() + 10
                while not events_file.exists() or "instrument " not in events_file.read_text():
                    if time.monotonic() >= end or process.poll() is not None:
                        process.kill()
                        self.fail("instrumentation did not start")
                    time.sleep(0.02)
                process.send_signal(interrupt)
            stdout, stderr = process.communicate(timeout=25)
        directory, = self.root.glob("little-buddy-oppo-*")
        report = json.loads((directory / "report.json").read_text())
        self.assertEqual(process.returncode, int(not report["passed"]), (stdout, stderr))
        with zipfile.ZipFile(directory / "oppo-report.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"summary.txt", "report.json", "junit.xml"})
            self.assertNotIn(b"secret", b"".join(archive.read(name) for name in archive.namelist()))
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(item.stat().st_mode & 0o777 == 0o600 for item in directory.iterdir()))
        self.assertFalse((self.root / "reverse").exists())
        return report, events_file.read_text().splitlines() if events_file.exists() else []

    def test_all_eight_one_master_and_ordered_cleanup(self):
        report, events = self.exercise("pass")
        self.assertEqual(report["counts"], {"PASS": 8})
        expected = ["master", "reverse"]
        for case in run.CASES:
            expected.extend([f"fixture {case}", f"instrument {case}", f"stop {case}"])
        self.assertEqual(events, [*expected, "remove"])

    def test_assumption_skip_and_selected_denominator(self):
        report, _ = self.exercise("skip", "--scenarios", "release,late,blackhole,disconnect")
        self.assertEqual(report["counts"], {"SKIP": 1, "NOT_RUN": 3})

    def test_assertion_failure_continues_after_confirmed_cleanup(self):
        report, events = self.exercise("fail", "--scenarios", "release,late", "--continue-on-failure")
        self.assertEqual(report["counts"], {"FAIL": 2})
        self.assertLess(events.index("stop release"), events.index("fixture late"))
        self.assertEqual(report["scenarios"][4]["timing"], ["event=segment_ack op=1 segment=1 ms=2000"])

    def test_crash_does_not_pass(self):
        report, _ = self.exercise("crash", "--scenarios", "release")
        self.assertEqual(report["counts"], {"FAIL": 1})

    def test_timeout_stops_instrumentation_and_fixture(self):
        report, events = self.exercise("timeout", "--scenarios", "release", "--timeout", "1")
        self.assertEqual(report["counts"], {"FAIL": 1})
        self.assertEqual(events[-3:], ["force-stop", "stop release", "remove"])

    def test_sigint_cleans_up(self):
        report, events = self.exercise("signal", "--scenarios", "release", interrupt=signal.SIGINT)
        self.assertIn("中断", report["error"])
        self.assertEqual(events[-3:], ["force-stop", "stop release", "remove"])

    def test_sigterm_cleans_up(self):
        report, events = self.exercise("signal", "--scenarios", "release", interrupt=signal.SIGTERM)
        self.assertIn("中断", report["error"])
        self.assertEqual(events[-3:], ["force-stop", "stop release", "remove"])

    def test_existing_reverse_is_preserved(self):
        report, events = self.exercise("reverse")
        self.assertIn("已有 9444 reverse", report["error"])
        self.assertEqual(events, [])

    def test_no_device(self):
        report, events = self.exercise("none")
        self.assertIn("没有匹配", report["error"])
        self.assertEqual(events, [])

    def test_multiple_devices(self):
        report, events = self.exercise("multi")
        self.assertIn("--serial", report["error"])
        self.assertEqual(events, [])

    def test_unauthorized_device(self):
        report, events = self.exercise("unauthorized")
        self.assertIn("USB 调试授权", report["error"])
        self.assertEqual(events, [])

    def test_port_occupied(self):
        with socket.socket() as port:
            port.bind(("127.0.0.1", 9444))
            port.listen()
            report, events = self.exercise("pass")
        self.assertIn("已被占用", report["error"])
        self.assertEqual(events, [])

    def test_password_failure(self):
        report, events = self.exercise("password")
        self.assertIn("SSH 登录", report["error"])
        self.assertEqual(events, ["master"])

    def test_ssh_disconnected(self):
        report, events = self.exercise("disconnect", "--scenarios", "release")
        self.assertEqual(report["counts"], {"FAIL": 1})
        self.assertEqual(events[-1], "remove")

    def test_zero_tests(self):
        output = subprocess.CompletedProcess([], 0, "OK (0 tests)\nINSTRUMENTATION_CODE: -1\n")
        self.assertEqual(run.classify(output)[0], "FAIL")


class RemoteLifecycle(unittest.TestCase):
    def test_ready_port_protection_and_stop_on_channel_eof(self):
        with tempfile.TemporaryDirectory(prefix="lb remote ") as directory:
            root = Path(directory)
            tools = root / "tools"
            tools.mkdir()
            for tool in ("sudo", "ss"):
                executable = tools / tool
                executable.write_text("#!" + sys.executable + "\n" + REMOTE_FAKE)
                executable.chmod(0o700)
            repo = root / "checkout ' with spaces"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "backend").mkdir()
            (repo / "backend" / "pinned.py").write_text("pinned_fixture = True\n")
            subprocess.run(["git", "-C", str(repo), "add", "backend"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture"],
                           check=True)
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                          text=True).strip()
            environment = dict(os.environ, HOME=str(root), FAKE_STATE=str(root),
                               PATH=str(tools) + os.pathsep + os.environ["PATH"])
            run_id = "a" * 32
            unit = f"little-buddy-regression-{run_id}-release.service"
            command = ["bash", str(run.HERE / "fixture-session.sh"), str(repo), sha, "release", run_id]
            (root / "occupied").touch()
            occupied = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=6)
            self.assertNotEqual(occupied.returncode, 0)
            self.assertEqual(occupied.stdout.strip(), "ERROR busy")
            self.assertFalse((root / "unit").exists())
            (root / "occupied").unlink()
            with subprocess.Popen(command, env=environment, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as fixture:
                run.read_ready(fixture, f"READY {unit}".encode())
                self.assertEqual((root / "unit").read_text(), unit)
                competitor = subprocess.run(command, env=environment, capture_output=True,
                                            text=True, timeout=6)
                self.assertEqual(competitor.stdout.strip(), "ERROR busy")
                output, error = fixture.communicate(timeout=6)  # close stdin, like a lost SSH channel
                self.assertEqual(fixture.returncode, 0, error)
                self.assertIn(f"STOPPED {unit}".encode(), output)
            self.assertFalse((root / "unit").exists())
            self.assertFalse(list(root.glob("stage-*")))


REMOTE_FAKE = r"""
import os, subprocess, sys, tempfile
from pathlib import Path

root = Path(os.environ["FAKE_STATE"])
if Path(sys.argv[0]).name == "ss":
    if (root / "occupied").exists():
        print("LISTEN 0 128 127.0.0.1:9444")
    sys.exit()
assert sys.argv[1] == "-n"
command, *args = sys.argv[2:]
unit = root / "unit"
if command == "mktemp":
    print(tempfile.mkdtemp(prefix="stage-", dir=root))
elif command == "systemd-run":
    path = next(item.split("=", 1)[1] for item in args if item.startswith("--working-directory="))
    assert (Path(path) / "backend" / "pinned.py").read_text() == "pinned_fixture = True\n"
    assert "RuntimeMaxSec=180s" in args
    assert args.count("backend.animal.private_fixture") == 1
    unit.write_text(next(item.split("=", 1)[1] for item in args if item.startswith("--unit=")))
elif command == "systemctl":
    assert args[-1] == unit.read_text()
    if args[0] == "stop":
        unit.unlink()
elif command == "journalctl":
    assert args[1] == unit.read_text()
    print("animal_fixture_ready scenario=release port=9444")
else:
    sys.exit(subprocess.call([command, *args]))
"""


if __name__ == "__main__":
    unittest.main()
