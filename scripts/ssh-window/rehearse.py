"""Run only inside the disposable systemd guest created by rehearse."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import socket
import subprocess as sp
import sys
import time

LAB = Path("/run/synthetic")
WINDOW = ["/usr/bin/python3", "-I", "/usr/local/libexec/tita-ssh-window.py"]
STATE = Path("/run/tita-ssh-window/private")
ROLLBACK = "tita-ssh-window.service"


def call(*args):
    return sp.check_output(args, text=True, timeout=10).strip()


def wait(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError("fixture condition timed out")


def ssh(user, key, *flags):
    return ["ssh", "-F", "/dev/null", "-o", "IdentitiesOnly=yes", "-o",
            "StrictHostKeyChecking=yes", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", f"UserKnownHostsFile={LAB}/known", "-o", "ConnectTimeout=3",
            "-i", str(LAB / key), *flags, f"{user}@127.0.0.1"]


def unknown():
    client = socket.create_connection(("127.0.0.1", 22), timeout=2)
    assert client.recv(256).startswith(b"SSH-2.0-")
    client.sendall(b"SSH-2.0-synthetic-fixture\r\n")
    return client


def listen():
    return tuple(call("ss", family, "-Hlnte", "sport = :22")
                 for family in ("-4", "-6"))


def denied():
    result = sp.run(ssh("labdevice", "device", "-o", "BatchMode=yes") + ["true"],
                    capture_output=True, timeout=5)
    assert result.returncode and b"Permission denied" in result.stderr, result.stderr


def pause_publication(mode):
    replace = os.replace

    def intercept(source, destination):
        if Path(destination).name != "device.pub":
            return replace(source, destination)
        if mode == "stalled-published":
            replace(source, destination)
        os.kill(os.getpid(), signal.SIGSTOP)
        if mode == "stalled-publish":
            replace(source, destination)

    os.replace = intercept
    sys.argv = [WINDOW[-1], "open"]
    runpy.run_path(WINDOW[-1], run_name="__main__")


def stalled(mode, management, inherited, hashes):
    key = STATE.parent / "device.pub"
    armed = time.monotonic()
    call("systemctl", "start", "tita-ssh-window.timer")
    opener = sp.Popen(["setsid", sys.executable, __file__, "pause-publication", mode])
    stopped, status = os.waitpid(opener.pid, os.WUNTRACED)
    assert stopped == opener.pid and os.WIFSTOPPED(status) and os.WSTOPSIG(status) == signal.SIGSTOP
    with (STATE / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("opener was not stopped while holding the lock")
    assert key.exists() == (mode == "stalled-published")
    if key.exists():
        device = sp.Popen(ssh("labdevice", "device", "-o", "BatchMode=yes", "-N"))
        wait(lambda: "Accepted publickey for labdevice " in
             call("journalctl", "-u", "ssh.service", "-o", "cat", "--no-pager"))
    else:
        device = None
    management()
    wait(lambda: (STATE / "draining").exists(), max(1, armed + 65 - time.monotonic()))
    elapsed = time.monotonic() - armed
    assert 59 <= elapsed <= 65 and not key.exists()
    assert (STATE / "rollback-started").exists()
    denied()
    if device:
        wait(lambda: device.poll() is not None)
    wait(lambda: call("systemctl", "show", ROLLBACK, "-p", "Result", "--value") == "success"
         and call("systemctl", "show", ROLLBACK, "-p", "ActiveState", "--value") == "inactive")
    assert (STATE / "result").read_text().strip() == "0"
    assert opener.poll() is None
    opener.send_signal(signal.SIGCONT)
    assert opener.wait(timeout=5) == 1
    assert not key.exists()
    denied()
    assert listen() == inherited
    assert hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in hashes}
    management()
    print(call("journalctl", "-u", ROLLBACK, "-o", "cat", "--no-pager"), flush=True)
    print(f"{mode}: opener stopped with lock; timer restored baseline after {elapsed:.1f}s; "
          "resumed opener could not publish; old/new management and inherited FDs verified", flush=True)


def main():
    assert Path("/proc/1/comm").read_text().strip() == "systemd"
    mode = sys.argv[1]
    for key in ("admin", "device"):
        call("ssh-keygen", "-q", "-t", "ed25519", "-N", "lab-only" if key == "device" and not mode.startswith("stalled-") else "",
             "-f", str(LAB / key))
    admin_key = Path("/run/synthetic-admin.pub")
    admin_key.write_bytes((LAB / "admin.pub").read_bytes())
    admin_key.chmod(0o644)
    (LAB / "known").write_text("127.0.0.1 " + Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text())
    files = [Path("/etc/ssh/sshd_config"), *Path("/etc/ssh/sshd_config.d").glob("*.conf")]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    (LAB / "hashes").write_text(json.dumps(hashes))
    (LAB / "contexts").write_text(json.dumps([["127.0.0.1", "127.0.0.1"], ["::1", "::1"]]))
    print(call(*WINDOW, "prepare", "labdevice", str(LAB / "device.pub"),
               str(LAB / "contexts"), str(LAB / "hashes")), flush=True)
    inherited = listen()
    admin = sp.Popen(ssh("labadmin", "admin", "-o", "BatchMode=yes") + ["cat"],
                     stdin=sp.PIPE, stdout=sp.PIPE)

    def management():
        admin.stdin.write(b"ok\n")
        admin.stdin.flush()
        assert admin.stdout.readline() == b"ok\n"
        assert call(*ssh("labadmin", "admin", "-o", "BatchMode=yes"), "printf ok") == "ok"
        with socket.create_connection(("::1", 22), timeout=2) as ipv6:
            assert ipv6.recv(256).startswith(b"SSH-2.0-")

    management()
    if mode.startswith("stalled-"):
        stalled(mode, management, inherited, hashes)
        return
    with unknown() as pending:
        # The same timer and service are used, with a separate initiating session.
        initiator = LAB / "initiator"
        initiator.write_text("#!/bin/sh\nset -eu\n"
                             "echo $$ >/run/synthetic/initiator.pid\n"
                             "systemctl start tita-ssh-window.timer\n"
                             + " ".join([*WINDOW, "open"]) + "\n")
        initiator.chmod(0o700)
        print(call("setsid", "--wait", str(initiator)), flush=True)
        pid = (LAB / "initiator.pid").read_text().strip()
        assert not Path(f"/proc/{pid}").exists()
        assert listen() == inherited
        management()
        call("openssl", "req", "-x509", "-newkey", "ed25519", "-nodes", "-days", "1",
             "-subj", "/CN=fixture.test", "-addext", "subjectAltName=DNS:fixture.test",
             "-keyout", str(LAB / "tls.key"), "-out", str(LAB / "tls.pem"))
        tls = sp.Popen(["openssl", "s_server", "-quiet", "-www", "-accept", "127.0.0.1:24457",
                        "-key", str(LAB / "tls.key"), "-cert", str(LAB / "tls.pem")])
        askpass = LAB / "askpass"
        askpass.write_text("#!/bin/sh\nprintf '%s\\n' lab-only\n")
        askpass.chmod(0o700)
        env = {**os.environ, "SSH_ASKPASS_REQUIRE": "force", "SSH_ASKPASS": str(askpass)}
        device = sp.Popen(ssh("labdevice", "device", "-N", "-o", "ExitOnForwardFailure=yes",
                              "-L", "127.0.0.1:24561:127.0.0.1:24457",
                              "-L", "127.0.0.1:24562:localhost:24457"),
                          env=env, stdin=sp.DEVNULL)

        def curl(port):
            return sp.run(["curl", "-q", "-fsS", "--noproxy", "*", "--max-time", "2",
                           "--cacert", str(LAB / "tls.pem"), "--resolve",
                           f"fixture.test:{port}:127.0.0.1", "-o", "/dev/null", "-w",
                           "%{http_code}", f"https://fixture.test:{port}/"], capture_output=True)

        wait(lambda: curl(24561).stdout == b"200")
        assert curl(24562).returncode != 0
        askpass.write_text("#!/bin/sh\n: >/run/synthetic/signing-paused\n"
                           "while test ! -e /run/synthetic/release-signing; do sleep .1; done\n"
                           "printf '%s\\n' lab-only\n")
        racer = sp.Popen(ssh("labdevice", "device", "-N"), stdin=sp.DEVNULL, env=env)
        wait(lambda: (LAB / "signing-paused").exists())
        wait(lambda: (STATE / "draining").exists(), 70)
        denied()
        (LAB / "release-signing").touch()
        wait(lambda: device.poll() is not None and racer.poll() is not None)
        assert curl(24561).returncode != 0 and racer.returncode != 0
        late = None
        if sys.argv[1] == "timeout":
            # 25 + 120 exceeds the 135-second rollback deadline.
            time.sleep(25)
            late = unknown()
        pending.settimeout(70)
        while pending.recv(4096):
            pass
        management()
        expected = 42 if late else 0
        wait(lambda: (STATE / "result").exists(), 145)
        assert int((STATE / "result").read_text()) == expected
        wait(lambda: call("systemctl", "show", ROLLBACK, "-p", "ActiveState", "--value")
             in {"inactive", "failed"})
        assert int(call("systemctl", "show", ROLLBACK, "-p", "ExecMainStatus", "--value")) == expected
        assert call("systemctl", "show", ROLLBACK, "-p", "Result", "--value") == (
            "exit-code" if late else "success")
        ssh_log = call("journalctl", "-u", "ssh.service", "-o", "cat", "--no-pager")
        assert ssh_log.count("Accepted publickey for labdevice ") == 1
        assert not Path("/run/tita-ssh-window/device.pub").exists()
        if late:
            late.settimeout(0.2)
            try:
                while late.recv(4096):
                    pass
            except TimeoutError:
                pass
            else:
                raise RuntimeError("late transport was closed before its grace period")
            late.close()
        assert listen() == inherited
        assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        denied()
        management()
        tls.terminate()
    print(call("journalctl", "-u", ROLLBACK, "-o", "cat", "--no-pager"), flush=True)
    print(f"isolated systemd: exit={expected}; timer outlived initiator; shared dual-stack FDs, "
          "baseline hashes and old/new management verified; fixed TLS only, revoke and race verified",
          flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "pause-publication":
        pause_publication(sys.argv[2])
        sys.exit(0)
    main()
    Path("/run/rehearsal-output/result").write_text("0\n")
