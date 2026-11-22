#!/usr/bin/env python3
"""Run the pinned offline Little Buddy scenarios from a Mac terminal."""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import select
import selectors
import shlex
import shutil
import signal
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
CASES = ("asr", "first-pcm", "between", "playing", "release", "late", "blackhole", "disconnect")
PORT = "tcp:9444"
REVERSE_TIMEOUT = 5
ARCHIVE_SHA = "$Format:%H$"
APP = "com.littlebuddy.sim"
TEST_APP = APP + ".test"
RUNNER = TEST_APP + "/com.littlebuddy.SimUiRunner"
TEST = "com.littlebuddy.AnimalPrivateActivityTest"
METHOD = "stopOrDisconnectClearsAndAllowsOnlyAManualNewGame"


class Failure(Exception):
    pass


class Interrupted(Failure):
    pass


def interrupt(number, _frame):
    # First signal requests orderly teardown. Subsequent signals cannot interrupt it.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise Interrupted("收到中断信号 " + str(number))


@contextmanager
def finish_cleanup():
    received = []

    def record(number, _frame):
        received.append(number)

    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        if signal.getsignal(sig) is interrupt:
            previous[sig] = signal.signal(sig, record)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if received:
            interrupt(received[0], None)


def invoke(command, stage, timeout=15):
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure(f"{stage}超时") from None
    except OSError:
        raise Failure(f"{stage}无法启动") from None


def checked(command, stage, timeout=15):
    result = invoke(command, stage, timeout)
    if result.returncode:
        raise Failure(f"{stage}失败（退出码 {result.returncode}）")
    return result.stdout


def digest(path):
    with path.open("rb") as source:
        sha = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def device_command(serial):
    rows = [line.split()[:2] for line in checked(["adb", "devices"], "ADB 设备枚举").splitlines()
            if len(line.split()) >= 2 and line.split()[1] in
            {"device", "unauthorized", "offline", "recovery", "sideload", "bootloader"}]
    if serial:
        rows = [row for row in rows if row[0] == serial]
    if len(rows) != 1:
        raise Failure("没有匹配的 ADB 设备" if not rows else "检测到多个设备，请用 --serial 指定 OPPO")
    selected, state = rows[0]
    if state == "unauthorized":
        raise Failure("请解锁 OPPO 并在手机上确认 USB 调试授权，再启动工具")
    if state != "device":
        raise Failure("指定设备未处于可用的 USB 调试状态")
    adb = ["adb", "-s", selected]
    if not re.fullmatch(r"usb:\S+", checked(adb + ["get-devpath"], "USB 连接检查").strip()):
        # Some macOS ADB backends omit the devpath. The USB-only selector can
        # still prove identity when exactly one USB device is attached.
        usb = invoke(["adb", "-d", "get-serialno"], "核验 USB 专用传输")
        if usb.returncode or usb.stdout.strip() != selected:
            raise Failure("无法核验 USB 连接，请仅保留已授权的 OPPO 数据线")
    return adb


def reverses(adb):
    rows = checked(adb + ["reverse", "--list"], "读取 ADB reverse").splitlines()
    return [row.split()[-1] for row in rows if len(row.split()) >= 3 and row.split()[-2] == PORT]


class ForwardToFixture(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.create_connection(("127.0.0.1", 9444), timeout=5) as tunnel:
                self.request.settimeout(5)
                readers = {self.request: tunnel, tunnel: self.request}
                while readers:
                    ready, _, _ = select.select(list(readers), [], [], 125)
                    if not ready:
                        break
                    for source in ready:
                        destination = readers[source]
                        data = source.recv(64 * 1024)
                        if data:
                            destination.sendall(data)
                        else:
                            destination.shutdown(socket.SHUT_WR)
                            del readers[source]
        except OSError:
            pass  # Instrumentation reports transport failures without logging payloads.


@contextmanager
def reverse_relay():
    # Keep this run's destination allocated until reverse reconciliation completes.
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), ForwardToFixture) as server:
        server.daemon_threads = True
        relay = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1})
        relay.start()
        try:
            yield f"tcp:{server.server_address[1]}"
        finally:
            server.shutdown()
            relay.join()


def remove_reverse(adb, destination, create_uncertain):
    # The source is shared. Only reconcile a mapping to our still-reserved port.
    # After timeout adbd may apply the request after the client has exited.
    idle_checks = 3 if create_uncertain else 1
    for _ in range(2):
        for attempt in range(idle_checks):
            mappings = reverses(adb)
            if mappings:
                break
            if attempt + 1 < idle_checks:
                time.sleep(0.2)
        if mappings != [destination]:
            return
        try:
            checked(adb + ["reverse", "--remove", PORT], "清理本次 ADB reverse", REVERSE_TIMEOUT)
        except Failure:
            # The device may already have removed it. Read back before retrying.
            pass
        idle_checks = 1
    if reverses(adb) == [destination]:
        raise Failure("无法确认本次 ADB reverse 已清理")


@contextmanager
def attached_reverse(adb, destination, cleanup_errors):
    if reverses(adb):
        raise Failure("设备已有 9444 reverse，本次保留原映射并退出")
    confirmed = False
    try:
        checked(adb + ["reverse", "--no-rebind", PORT, destination],
                "新增 ADB reverse", REVERSE_TIMEOUT)
        if reverses(adb) != [destination]:
            raise Failure("未能确认本次 ADB reverse")
        confirmed = True
        yield
    finally:
        with finish_cleanup():
            try:
                remove_reverse(adb, destination, create_uncertain=not confirmed)
            except Failure as exc:
                cleanup_errors.append(str(exc))


def verify_packages(adb, options, manifest):
    for package, (name, expected) in zip((APP, TEST_APP), manifest["apk"].items()):
        if options.install:
            flags = ["-r", "-g"] if package == APP else ["-r"]
            output = checked(adb + ["install", *flags, str(options.apk_dir / name)], "覆盖安装 " + package, 90)
            if "Success" not in output.splitlines():
                raise Failure("覆盖安装未返回 Success")
        lines = checked(adb + ["shell", "pm", "path", package], "读取已安装 APK 路径").splitlines()
        if len(lines) != 1 or not re.fullmatch(r"package:/[a-zA-Z0-9_=/+.~:-]+/base\.apk", lines[0]):
            raise Failure("缺少已安装的单包 APK，请检查安装或使用 --install")
        path = shlex.quote(lines[0][len("package:"):])
        fields = checked(adb + ["shell", "sha256sum", path], "核验设备 APK 字节").split()
        if not fields or fields[0] != expected:
            raise Failure("设备 APK 与审定附件哈希不符，请使用 --apk-dir 和 --install")
    runners = checked(adb + ["shell", "pm", "list", "instrumentation", APP], "检查测试 runner")
    if f"instrumentation:{RUNNER} (target={APP})" not in runners.splitlines():
        raise Failure("已安装测试 runner 或目标包不匹配")


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@contextmanager
def connection(target, cleanup_errors):
    with tempfile.TemporaryDirectory(prefix="lb-ssh-", dir="/tmp") as directory:
        control = Path(directory, "ctl")
        ssh = ["ssh", "-F", "/dev/null", "-S", str(control),
               "-o", "StrictHostKeyChecking=ask", "-o", "ConnectTimeout=10",
               "-o", "NumberOfPasswordPrompts=1", "-o", "ServerAliveInterval=5",
               "-o", "ServerAliveCountMax=2"]
        # OpenSSH owns terminal authentication, then detaches the master with -f.
        # The dedicated control socket lets us exit only after fixture teardown.
        master = subprocess.Popen(
            ssh + ["-f", "-M", "-N", "-o", "ControlPersist=150", "-o", "ExitOnForwardFailure=yes",
                   "-L", "127.0.0.1:9444:127.0.0.1:9444", "--", target],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        try:
            try:
                status = master.wait(timeout=60)
            except subprocess.TimeoutExpired:
                raise Failure("等待 SSH 登录超时") from None
            if status:
                raise Failure("SSH 登录或 9444 转发失败")
            checked(ssh + ["-O", "check", "--", target], "检查 SSH 控制连接", 5)
            yield ssh + ["-T", "-o", "BatchMode=yes", "-o", "ProxyCommand=false", "--", target]
        finally:
            with finish_cleanup():
                stop_process(master)
                if control.exists():
                    try:
                        checked(ssh + ["-O", "exit", "--", target], "关闭专属 SSH 连接", 5)
                    except Failure as exc:
                        if control.exists():
                            cleanup_errors.append(str(exc) + "，空闲连接最长保留 150 秒")


def read_ready(process, marker):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        end = time.monotonic() + 20
        output = b""
        while time.monotonic() < end and len(output) < 4096:
            if not selector.select(max(0, end - time.monotonic())):
                break
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            output += chunk
            lines = output.splitlines()
            if marker in lines and process.poll() is None:
                return
            if b"ERROR busy" in lines:
                raise Failure("服务器 9444 已有服务或回归会话，本次未接管")
            if b"ERROR checkout" in lines:
                raise Failure("服务器检出缺少审定的夹具提交，请核对 --checkout")
    raise Failure("远端夹具未就绪，请检查固定提交、9444 占用及服务依赖")


@contextmanager
def fixture(ssh, options, manifest, run, scenario, cleanup_errors):
    script = (HERE / "fixture-session.sh").read_text(encoding="utf-8")
    command = shlex.join(["bash", "-c", script, "fixture-session", options.checkout,
                          manifest["fixture_sha"], scenario, run])
    unit = f"little-buddy-regression-{run}-{scenario}.service"
    with subprocess.Popen(ssh + [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        ready = False
        try:
            read_ready(process, f"READY {unit}".encode())
            ready = True
            yield process
        finally:
            with finish_cleanup():
                try:
                    # EOF also reaches the remote session when the local SSH connection is lost.
                    output, _ = process.communicate(input=b"STOP\n", timeout=12)
                    if ready and (process.returncode or f"STOPPED {unit}".encode() not in output.splitlines()):
                        cleanup_errors.append(f"{scenario} 夹具停止未确认，远端单元最长运行 180 秒")
                    elif f"CLEANUP_FAILED {unit}".encode() in output.splitlines():
                        cleanup_errors.append(f"{scenario} 远端夹具清理失败")
                    elif not ready and process.returncode == 255:
                        cleanup_errors.append(f"{scenario} SSH 断开，远端单元最长运行 180 秒")
                except subprocess.TimeoutExpired:
                    stop_process(process)
                    cleanup_errors.append(f"{scenario} 夹具清理超时，远端单元最长运行 180 秒")


def classify(result):
    output = result.stdout
    status = re.findall(r"^INSTRUMENTATION_STATUS_CODE: (-?\d+)\s*$", output, re.M)
    final = re.findall(r"^INSTRUMENTATION_CODE: (-?\d+)\s*$", output, re.M)
    classes = re.findall(r"^INSTRUMENTATION_STATUS: class=(\S+)\s*$", output, re.M)
    tests = re.findall(r"^INSTRUMENTATION_STATUS: test=(\S+)\s*$", output, re.M)
    counts = re.findall(r"^INSTRUMENTATION_STATUS: numtests=(\d+)\s*$", output, re.M)
    ok = bool(re.search(r"^OK \(1 tests?\)\s*$", output, re.M))
    failure = bool(re.search(r"^FAILURES!!!|^INSTRUMENTATION_FAILED:|^INSTRUMENTATION_ABORTED:|"
                             r"^INSTRUMENTATION_RESULT: shortMsg=|^INSTRUMENTATION_STATUS: Error=",
                             output, re.M))
    evidence = {"adb_exit": result.returncode, "status_codes": status[:8], "final_codes": final[:4],
                "ok_one_test": ok, "runner_error": failure}
    assertion = re.search(
        r"Private route condition not reached \(image=(?:true|false) startEnabled=(?:true|false)"
        r" releasePending=\d{1,6} playedHeads=\d{1,6} segmentConfirmed=\d{1,6}"
        r" turnCommitted=\d{1,6} captureDispatch=\d{1,6}\)", output)
    if assertion:
        evidence["assertion"] = assertion[0]
    locations = re.findall(r"\(AnimalPrivateActivityTest\.kt:(\d{1,4})\)", output)
    if locations:
        evidence["test_lines"] = list(dict.fromkeys(int(line) for line in locations))[:8]
    if result.returncode or final != ["-1"] or failure:
        return "FAIL", "runner 失败、断连或结果不完整", evidence
    if status in (["1", "-4"], ["1", "-3"], ["-3"]):
        return "SKIP", "runner 跳过用例或 assumption 未满足", evidence
    if (status == ["1", "0"] and ok and classes == [TEST, TEST] and tests == [METHOD, METHOD]
            and counts == ["1", "1"]):
        return "PASS", "", evidence
    return "FAIL", "断言失败、未执行指定用例或结果不完整", evidence


def timing_events(adb, uptime):
    # Keep only pinned AnimalTiming event names and numeric fields after this case began.
    if uptime.returncode or not re.fullmatch(r"\d+\.\d+ \d+\.\d+\s*", uptime.stdout):
        return []
    since = int(float(uptime.stdout.split()[0]) * 1000)
    try:
        log = checked(adb + ["shell", "logcat", "-d", "-t", "200", "-v", "raw",
                             "-s", "AnimalTiming:I", "'*:S'"], "读取 AnimalTiming", 5)
    except Failure:
        return []
    pattern = re.compile(
        r"event=(?:segment_drained|segment_ack|segment_confirmed|release_notice|"
        r"release_applied|playback_head_first_advance|capture_sealed)"
        r" op=\d{1,19}(?: segment=\d{1,4})? ms=(\d{1,19})")
    return [line for line in log.splitlines() if (match := pattern.fullmatch(line))
            and int(match[1]) > since][-50:]


def test_scenario(adb, ssh, options, manifest, report, row):
    begin = time.monotonic()
    scenario = row["scenario"]
    errors = report["cleanup_errors"]
    previous_errors = len(errors)
    try:
        with fixture(ssh, options, manifest, report["run_id"], scenario, errors) as remote:
            completed = False
            uptime = invoke(adb + ["shell", "cat", "/proc/uptime"], "读取设备启动时钟", 5)
            try:
                result = invoke(adb + ["shell", "am", "instrument", "-w", "-r",
                                       "-e", "class", TEST, "-e", "animalScenario", scenario, RUNNER],
                                "instrumentation", options.timeout)
                completed = result.returncode == 0
                row["status"], row["error"], row["runner"] = classify(result)
                if remote.poll() is not None:
                    raise Failure("运行中夹具或 SSH 连接退出")
            finally:
                if not completed:
                    try:
                        checked(adb + ["shell", "am", "force-stop", APP], "停止本次测试应用", 8)
                    except Failure as exc:
                        errors.append(str(exc))
                if row["status"] != "PASS":
                    row["timing"] = timing_events(adb, uptime)
    except Failure as exc:
        row.update(status="FAIL", error=str(exc))
        if isinstance(exc, Interrupted):
            raise
    finally:
        row["seconds"] = round(time.monotonic() - begin, 3)
        if len(errors) != previous_errors and row["status"] == "PASS":
            row.update(status="FAIL", error="场景清理未确认")


def run(options, manifest, report):
    for tool in ("adb", "ssh"):
        if not shutil.which(tool):
            raise Failure(f"找不到 {tool}，请在普通终端配置 PATH")
    if options.apk_dir:
        for name, expected in manifest["apk"].items():
            if digest(options.apk_dir / name) != expected:
                raise Failure("本地 APK SHA-256 不匹配：" + name)
    adb = device_command(options.serial)
    if reverses(adb):
        raise Failure("设备已有 9444 reverse，本次保留原映射并退出")
    with socket.socket() as probe:
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", 9444))
        except OSError:
            raise Failure("Mac 回环 9444 已被占用，本次未接管") from None
    verify_packages(adb, options, manifest)
    report["installed_apks_verified"] = True
    cleanup_errors = report["cleanup_errors"]
    with connection(options.ssh_target, cleanup_errors) as ssh, reverse_relay() as destination:
        with attached_reverse(adb, destination, cleanup_errors):
            for row in report["scenarios"]:
                if row["status"] == "NOT_REQUESTED":
                    continue
                print(f"运行 {row['scenario']}…", flush=True)
                test_scenario(adb, ssh, options, manifest, report, row)
                if cleanup_errors or (row["status"] != "PASS" and not options.keep_going):
                    break


def tool_sha():
    if re.fullmatch(r"[0-9a-f]{40}", ARCHIVE_SHA):
        return ARCHIVE_SHA
    try:
        sha = checked(["git", "-C", str(HERE), "rev-parse", "HEAD"], "读取工具提交", 3).strip()
    except Failure:
        return None
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


def write_report(directory, report):
    rows = report["scenarios"]
    selected = [row for row in rows if row["status"] != "NOT_REQUESTED"]
    counts = Counter(row["status"] for row in selected)
    report["counts"] = dict(counts)
    report["passed"] = (counts["PASS"] == len(selected) and not report["error"]
                        and not report["cleanup_errors"])
    lifecycle_error = int(bool(report["error"] or report["cleanup_errors"]))
    suite = ET.Element("testsuite", name="Little Buddy OPPO", tests=str(len(selected) + lifecycle_error),
                       failures=str(counts["FAIL"]), skipped=str(counts["SKIP"] + counts["NOT_RUN"]),
                       errors=str(lifecycle_error))
    for row in selected:
        test = ET.SubElement(suite, "testcase", name=row["scenario"], time=str(row.get("seconds", 0)))
        if row["status"] == "FAIL":
            ET.SubElement(test, "failure", message=row["error"])
        elif row["status"] != "PASS":
            ET.SubElement(test, "skipped", message=row.get("error") or "未执行")
    if lifecycle_error:
        lifecycle = ET.SubElement(suite, "testcase", name="run_lifecycle")
        ET.SubElement(lifecycle, "error", message=" / ".join(
            [message for message in [report["error"], *report["cleanup_errors"]] if message]))
    (directory / "junit.xml").write_bytes(ET.tostring(suite, encoding="utf-8", xml_declaration=True))
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    summary = [f"{'PASS' if report['passed'] else 'FAIL'} · 已请求 {len(selected)} 项",
               f"运行 {report['run_id']} · APK {report['version']} · 夹具 {report['fixture_sha']}",
               f"工具提交 {report['tool_sha'] or '未知'}",
               f"通过 {counts['PASS']}，失败 {counts['FAIL']}，跳过 {counts['SKIP']}，未执行 {counts['NOT_RUN']}"]
    for row in rows:
        summary.append(f"{row['scenario']} {row['status']}  {row.get('seconds', 0):.3f}s  {row.get('error', '')}")
    summary.extend(message for message in [report["error"], *report["cleanup_errors"]] if message)
    (directory / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    with zipfile.ZipFile(directory / "oppo-report.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("summary.txt", "report.json", "junit.xml"):
            archive.write(directory / name, name)
    print("\n".join(summary))
    print(f"可分享的报告包 {directory / 'oppo-report.zip'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", default="ubuntu@43.139.76.15")
    parser.add_argument("--checkout", required=True, help="服务器现有 Git 检出的绝对路径")
    parser.add_argument("--serial")
    parser.add_argument("--apk-dir", type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--scenarios", default=",".join(CASES))
    parser.add_argument("--continue-on-failure", dest="keep_going", action="store_true")
    parser.add_argument("--timeout", type=int, default=90, help="单个 instrumentation 超时秒数（1–120）")
    options = parser.parse_args()
    requested = options.scenarios.split(",")
    if len(set(requested)) != len(requested) or not set(requested) <= set(CASES):
        parser.error("--scenarios 需要逗号分隔的已知场景，且不能重复")
    if not options.checkout.startswith("/") or not re.fullmatch(
            r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*", options.ssh_target):
        parser.error("需要绝对 --checkout 路径和合法的 SSH 目标（user@host）")
    if not 1 <= options.timeout <= 120 or (options.install and not options.apk_dir):
        parser.error("--timeout 必须在 1–120；--install 必须指定 --apk-dir")
    if options.apk_dir:
        options.apk_dir = options.apk_dir.resolve()
    os.umask(0o077)
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    directory = Path(tempfile.mkdtemp(prefix="little-buddy-oppo-", dir=Path.cwd()))
    report = dict(manifest, tool_sha=tool_sha(), run_id=uuid.uuid4().hex, device="USB Android（标识已省略）",
                  installed_apks_verified=False, error="", cleanup_errors=[],
                  scenarios=[{"scenario": case, "status": "NOT_RUN" if case in requested else "NOT_REQUESTED"}
                             for case in CASES])
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupt)
    try:
        run(options, manifest, report)
    except Failure as exc:
        report["error"] = str(exc)
    except OSError as exc:
        report["error"] = f"本地文件或进程操作失败（错误号 {exc.errno}）"
    finally:
        write_report(directory, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
