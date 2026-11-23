#!/usr/bin/env python3
"""Single-use, root-operated rollback for the reviewed Ubuntu SSH topology."""

import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time

STATE = Path("/run/tita-ssh-window")
PRIVATE = STATE / "private"
KEY = STATE / "device.pub"
CONFIG = Path("/etc/ssh/sshd_config")
INCLUDES = CONFIG.parent / "sshd_config.d"
SSHD = "/usr/sbin/sshd"
SERVICE = "tita-ssh-window.service"
TIMER = "tita-ssh-window.timer"
RULES = {
    "AuthenticationMethods": "publickey", "PubkeyAuthentication": "yes",
    "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
    "HostbasedAuthentication": "no", "GSSAPIAuthentication": "no",
    "AuthorizedKeysFile": str(KEY), "AuthorizedKeysCommand": "none",
    "TrustedUserCAKeys": "none", "PubkeyAcceptedAlgorithms": "ssh-ed25519",
    "MaxSessions": "0", "PermitTTY": "no", "AllowAgentForwarding": "no",
    "X11Forwarding": "no", "AllowTcpForwarding": "local",
    "PermitOpen": "127.0.0.1:24457", "PermitListen": "none",
    "AllowStreamLocalForwarding": "no", "PermitTunnel": "no", "PermitUserRC": "no",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def output(*command, timeout=4):
    return subprocess.check_output(command, text=True, timeout=timeout).strip()


def prop(unit, name):
    return output("systemctl", "show", unit, "--property", name, "--value")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def config_files():
    directory = INCLUDES.lstat()
    require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == 0
            and not directory.st_mode & 0o022, "unsafe SSH Include directory")
    files = [CONFIG, *sorted(INCLUDES.glob("*.conf"))]
    hashes = {}
    for path in files:
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
                and not metadata.st_mode & 0o022, "unsafe SSH configuration file")
        data = path.read_bytes()
        includes = []
        for line in data.decode().splitlines():
            tokens = shlex.split(line, comments=True)
            if tokens and re.fullmatch(r"(?i)include(?:=.*)?", tokens[0]):
                includes.append(tokens)
        allowed = [["Include", "/etc/ssh/sshd_config.d/*.conf"]] if path == CONFIG else []
        require(includes == allowed, "unexpected Include topology")
        hashes[str(path)] = digest(data)
    return hashes


def atomic(path, data, mode, group=0):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".ssh-window-")
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def proc(pid):
    directory = Path(f"/proc/{pid}")
    try:
        fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        title = (directory / "cmdline").read_bytes().split(b"\0", 1)[0]
        return int(fields[1]), fields[19], title
    except (ProcessLookupError, FileNotFoundError):
        return None


def socket_inodes(pid):
    inodes = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(fd)
        except (FileNotFoundError, ProcessLookupError):
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match:
            inodes.add(match[1])
    return inodes


def listener():
    require(prop("ssh.socket", "ActiveState") == "active"
            and prop("ssh.socket", "Accept") == "no", "expected active Accept=no ssh.socket")
    require(set(prop("ssh.socket", "Listen").splitlines())
            == {"0.0.0.0:22 (Stream)", "[::]:22 (Stream)"}, "unexpected socket configuration")
    require(prop("ssh.service", "ActiveState") == "active", "ssh.service inactive")
    pid = int(prop("ssh.service", "MainPID"))
    info = proc(pid) if pid > 1 else None
    require(info and info[0] == 1 and info[2].startswith(b"sshd: /usr/sbin/sshd -D [listener]"),
            "unexpected SSH listener command")
    env = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    require(not any(entry.startswith(b"SSHD_OPTS=") and entry != b"SSHD_OPTS=" for entry in env),
            "unexpected SSHD_OPTS")
    inherited = socket_inodes(pid) & socket_inodes(1)
    live = set()
    for family, address in (("-4", "0.0.0.0:22"), ("-6", "[::]:22")):
        rows = output("ss", family, "-Hlnte", "sport = :22").splitlines()
        require(len(rows) == 1 and rows[0].split()[3] == address, "unexpected TCP listener")
        inode = re.search(r"\bino:(\d+)", rows[0])
        require(inode and inode[1] in inherited, "listener FD is not shared with PID 1")
        live.add(inode[1])
    return [pid, info[1], sorted(live)]


def effective(path, user, context):
    host, peer, local = context
    return output(SSHD, "-T", "-D", "-f", str(path), "-C",
                  f"user={user},host={host},addr={peer},laddr={local},lport=22")


def matrix(candidate, device, contexts):
    accounts = {line.split(":", 1)[0] for line in output("getent", "passwd").splitlines()}
    require(device in accounts and len(accounts) > 1, "device or management accounts missing")
    for context in contexts:
        for account in sorted(accounts - {device}):
            old = effective(CONFIG, account, context)
            require(old == effective(candidate, account, context)
                    and "usedns no" in old.splitlines()
                    and "logingracetime 120" in old.splitlines(), "non-device matrix differs")
        base = dict(line.split(" ", 1) for line in effective(CONFIG, device, context).splitlines())
        new = dict(line.split(" ", 1) for line in effective(candidate, device, context).splitlines())
        require(str(KEY) not in base["authorizedkeysfile"].split()
                and base["authorizedkeyscommand"] == "none"
                and base["trustedusercakeys"] == "none"
                and new["logingracetime"] == "120"
                and new["disableforwarding"] == "no"
                and all(new.get(key.lower()) == value for key, value in RULES.items()),
                "device policy differs from the reviewed restrictions")
    print(f"matrix: {len(accounts)-1} non-device accounts × {len(contexts)} contexts; "
          f"{len(RULES)} device restrictions per context", flush=True)


def prepare(device, key_path, context_path, manifest_path):
    require(re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", device) and device != "root",
            "dedicated device login required")
    require(int(output("id", "-u", device)) >= 1000, "device must be unprivileged")
    public_key = Path(key_path).read_bytes()
    require(re.fullmatch(rb"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?\n?", public_key),
            "expected exactly one plain Ed25519 public key")
    output("ssh-keygen", "-lf", key_path)
    pairs = json.loads(Path(context_path).read_text())
    require(isinstance(pairs, list) and pairs, "provide reviewed numeric peer/local pairs")
    contexts = [("localhost", "127.0.0.1", "127.0.0.1"), ("localhost", "::1", "::1"),
                ("192.0.2.5", "192.0.2.5", "198.51.100.8"),
                ("client.example", "192.0.2.5", "198.51.100.8"),
                ("2001:db8::5", "2001:db8::5", "2001:db8::8"),
                ("client.example", "2001:db8::5", "2001:db8::8")]
    for peer, local in pairs:
        peer, local = (str(ipaddress.ip_address(value)) for value in (peer, local))
        contexts.append((peer, peer, local))
    hashes = config_files()
    require(hashes == json.loads(Path(manifest_path).read_text()),
            "configuration hashes differ from reviewed snapshot")
    daemon = listener()
    baseline = CONFIG.read_bytes()
    require(digest(baseline) == hashes[str(CONFIG)], "configuration drift")
    metadata = CONFIG.stat()
    candidate = baseline + (f"\nMatch User {device}\n" +
                            "".join(f"    {key} {value}\n" for key, value in RULES.items())).encode()
    require(not (PRIVATE / "plan").exists() and not KEY.exists(), "window already prepared")
    atomic(PRIVATE / "baseline", baseline, 0o600)
    atomic(PRIVATE / "candidate", candidate, 0o600)
    atomic(PRIVATE / "staged-key", public_key, 0o600)
    for path in (PRIVATE / "baseline", PRIVATE / "candidate"):
        output(SSHD, "-t", "-D", "-f", str(path))
    matrix(PRIVATE / "candidate", device, contexts)
    require(config_files() == hashes and listener() == daemon, "preflight drift")
    plan = {"device": device, "hashes": hashes, "daemon": daemon,
            "mode": stat.S_IMODE(metadata.st_mode), "group": metadata.st_gid,
            "candidate": digest(candidate), "key": digest(public_key)}
    atomic(PRIVATE / "plan", json.dumps(plan).encode(), 0o600)


def reload_ssh(daemon):
    cursor = output("journalctl", "-b", "-u", "ssh.service", "-n", "1",
                    "--show-cursor", "--no-pager").splitlines()[-1]
    require(cursor.startswith("-- cursor: "), "SSH journal cursor unavailable")
    output("systemctl", "reload", "ssh.service")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            log = output("journalctl", "-b", "-u", "ssh.service",
                         "--after-cursor", cursor.removeprefix("-- cursor: "),
                         "-o", "cat", "--no-pager")
            if ("Received SIGHUP" in log and "Server listening on 0.0.0.0 port 22." in log
                    and "Server listening on :: port 22." in log and listener() == daemon):
                return
        except RuntimeError:
            pass
        time.sleep(0.05)
    raise RuntimeError("SSH reload did not retain both inherited listeners")


def verify_arm():
    require(prop(TIMER, "SubState") == "waiting"
            and prop(TIMER, "Unit") == SERVICE
            and prop(SERVICE, "ActiveState") == "inactive"
            and prop(SERVICE, "RuntimeMaxUSec") == "2min 35s"
            and ("argv[]=/usr/bin/python3 -I /usr/local/libexec/tita-ssh-window.py rollback ;"
                 in prop(SERVICE, "ExecStart")),
            "independent rollback unit not armed with expected command and limit")
    timespan = output("systemd-analyze", "timespan", prop(TIMER, "NextElapseUSecMonotonic"))
    elapsed = re.search(r"(?m)^\s*μs:\s*(\d+)$", timespan)
    require(elapsed, "rollback timer deadline unavailable")
    deadline = int(elapsed[1]) / 1_000_000
    require(10 <= deadline - time.monotonic() <= 61, "unexpected rollback timer deadline")
    print(f"rollback armed: monotonic deadline={deadline:.3f}", flush=True)


def inventory(daemon, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("drain deadline")
    rows = output("ss", "-Htnp", "state", "established", "sport = :22",
                  timeout=min(4, remaining))
    owners = set(map(int, re.findall(r"pid=(\d+)", rows)))
    children = Path(f"/proc/{daemon}/task/{daemon}/children").read_text().split()
    return {pid: (info, pid in owners) for pid in owners | set(map(int, children))
            if (info := proc(pid)) and info[0] == daemon}


def drain(plan, started):
    daemon = plan["daemon"][0]
    target = f"sshd: {plan['device']} [priv]".encode()
    quiet = 0
    signaled = set()
    pending = 0
    deadline = started + 135
    try:
        while time.monotonic() < deadline:
            info = proc(daemon)
            require(info and info[1] == plan["daemon"][1], "SSH listener identity changed")
            connections = inventory(daemon, deadline)
            pending = 0
            for pid, (identity, owns_socket) in connections.items():
                title = identity[2]
                if title != target and re.fullmatch(rb"sshd: [^ ]+ \[priv\]", title):
                    continue
                pending += 1
                if title != target or not owns_socket:
                    continue
                try:
                    fd = os.pidfd_open(pid)
                    try:
                        if (inventory(daemon, deadline).get(pid) == (identity, True)
                                and time.monotonic() < deadline):
                            signal.pidfd_send_signal(fd, signal.SIGTERM)
                            signaled.add((pid, identity[1]))
                    finally:
                        os.close(fd)
                except ProcessLookupError:
                    pass
            quiet = quiet + 1 if pending == 0 else 0
            if quiet >= 4 and time.monotonic() < deadline:
                break
            time.sleep(max(0, min(0.1, deadline - time.monotonic())))
    except (TimeoutError, subprocess.TimeoutExpired):
        if time.monotonic() < deadline:
            raise
        quiet = 0
    result = 0 if quiet >= 4 and time.monotonic() < deadline else 42
    print(f"drain: elapsed={time.monotonic()-started:.1f}s "
          f"signaled={len(signaled)} pending={pending} exit={result}", flush=True)
    return result


def open_window(plan):
    require(not (PRIVATE / "rollback-started").exists() and not KEY.exists()
            and not (PRIVATE / "opening").exists(), "window already used")
    require(config_files() == plan["hashes"] and listener() == plan["daemon"], "preflight drift")
    verify_arm()
    candidate = (PRIVATE / "candidate").read_bytes()
    key = (PRIVATE / "staged-key").read_bytes()
    require(digest(candidate) == plan["candidate"] and digest(key) == plan["key"],
            "staged artifact drift")
    (PRIVATE / "opening").touch(exist_ok=False)
    atomic(CONFIG, candidate, plan["mode"], plan["group"])
    reload_ssh(plan["daemon"])
    verify_arm()
    atomic(KEY, key, 0o644)
    print("device key published", flush=True)


def rollback(plan):
    (PRIVATE / "rollback-started").touch()
    restored = False
    try:
        hashes = config_files()
        baseline = (PRIVATE / "baseline").read_bytes()
        require(digest(baseline) == plan["hashes"][str(CONFIG)], "backup hash mismatch")
        current = hashes.pop(str(CONFIG))
        if current == plan["candidate"]:
            atomic(CONFIG, baseline, plan["mode"], plan["group"])
        else:
            require(current == plan["hashes"][str(CONFIG)], "unexpected active config; key revoked")
        require(config_files() == plan["hashes"], "Include drift; key revoked")
        if (PRIVATE / "opening").exists():
            reload_ssh(plan["daemon"])
        restored = True
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"baseline restore failed: {error}", flush=True)
    print(f"rollback: key_absent={not KEY.exists()} baseline_reloaded={restored}", flush=True)
    started = time.monotonic()
    (PRIVATE / "draining").touch()
    drained = drain(plan, started)
    result = drained if restored or drained == 42 else 1
    atomic(PRIVATE / "result", f"{result}\n".encode(), 0o600)
    return result


def main():
    require(os.geteuid() == 0, "root required")
    action, *args = sys.argv[1:]
    STATE.mkdir(mode=0o711, exist_ok=True)
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    for path, mode in ((STATE, 0o711), (PRIVATE, 0o700)):
        metadata = path.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                and stat.S_IMODE(metadata.st_mode) == mode, "unsafe state directory")
    with (PRIVATE / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "prepare" and len(args) == 4:
            prepare(*args)
        elif action in {"open", "rollback"} and not args:
            if action == "rollback":
                KEY.unlink(missing_ok=True)
            plan = json.loads((PRIVATE / "plan").read_text())
            if action == "open":
                open_window(plan)
            else:
                return rollback(plan)
        elif action == "verify-arm" and not args:
            verify_arm()
        else:
            raise RuntimeError("expected prepare DEVICE KEY CONTEXTS HASH_MANIFEST, verify-arm, open or rollback")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"ssh-window: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
