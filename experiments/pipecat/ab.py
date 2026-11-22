"""Run two isolated workers, granting one 8444 listener at a time."""

import asyncio
import io
import json
import os
import re
import resource
import ssl
import statistics
import sys
from contextlib import redirect_stdout
from pathlib import Path
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from backend.dashscope import DashScope, GreetingPolicy, http_client
from backend.server import voice_server
from backend.wire import HEADER

PORT = 8444
FRAME_BYTES = 640  # 20 ms mono PCM s16le at 16 kHz.
ROUNDS = 3  # One cold and two subsequent attempts per arm.
TIMING = re.compile(r"voice_timing ([a-z0-9_]+) turn_id=([a-f0-9-]{36}) "
                    r"connection_id=[a-f0-9-]{36} segment=([0-8]) since_connect_ms=(\d+)")
EXPECTED = ("fun-asr-realtime", "qwen3.8-flash", "cosyvoice-v3-flash", "longanyang")


def rss_kib():
    return next(int(line.split()[1]) for line in Path("/proc/self/status").read_text().splitlines()
                if line.startswith("VmRSS:"))


async def trial(audio, token, trust, turn):
    headers = {"Authorization": "Bearer " + token, "X-Voice-Turn-ID": turn}
    async with connect(f"wss://localhost:{PORT}/v1/turn", host="127.0.0.1",
                       additional_headers=headers, ssl=trust, proxy=None) as socket:
        if json.loads(await socket.recv()) != {"v": 1, "type": "turn.ready"}:
            return "invalid_ready"
        for offset in range(0, len(audio), FRAME_BYTES):
            chunk = audio[offset:offset + FRAME_BYTES]
            await socket.send(HEADER.pack(1, 1, offset // 2) + chunk)
            await asyncio.sleep(len(chunk) / 32000)
        await socket.send(json.dumps({"v": 1, "type": "turn.end", "samples": len(audio) // 2}))
        segments = 0
        async for message in socket:
            if isinstance(message, str):
                control = json.loads(message)
                if control["type"] == "segment.end":
                    segments += 1
                if control["type"] == "reply.end":
                    await socket.wait_closed()
                    return "ok" if segments == control["count"] == 2 else "unexpected_segment_count"
        return "closed_before_reply"


def timings(output, turn):
    events = {}
    for line in output.splitlines():
        match = TIMING.fullmatch(line)
        if match and match[2] == turn:
            events[f"{match[1]}:{match[3]}"] = int(match[4])
    deltas = {}
    for label, start, end in (
        ("seal_to_asr", "capture_sealed:0", "asr_final:0"),
        ("asr_to_approved", "asr_final:0", "llm_approved_segment:1"),
        ("approved_to_pcm", "llm_approved_segment:1", "tts_first_pcm:1"),
        ("pcm_to_send", "tts_first_pcm:1", "first_pcm_sent:1"),
        ("seal_to_pcm", "capture_sealed:0", "tts_first_pcm:1"),
        ("seal_to_send", "capture_sealed:0", "first_pcm_sent:1"),
        ("segment_gap", "segment_sent:1", "first_pcm_sent:2"),
    ):
        if start in events and end in events:
            deltas[label] = events[end] - events[start]
    return {"events_ms": events, "deltas_ms": deltas}


def matches_config(provider):
    return ((provider.asr, provider.llm, provider.tts, provider.voice) == EXPECTED
            and provider.ws_url.split("/")[2].endswith(".cn-beijing.maas.aliyuncs.com"))


async def seed_audio():
    # Python 3.12 has a streaming PCM resampler in the standard library.
    import audioop

    async with http_client() as http, asyncio.timeout(10):
        provider = DashScope.from_environment(http)
        if not matches_config(provider):
            raise ValueError("configuration mismatch")
        pcm = bytearray()
        # A single TTS request generates the common input. Both measured
        # workers still use the same unmodified ASR, policy, LLM and TTS.
        async with provider.synthesize("你好，瓦力。", 24000) as frames:
            async for frame in frames:
                pcm.extend(frame)
                if len(pcm) > 480000:
                    raise ValueError("oversized synthetic input")
        audio, _ = audioop.ratecv(bytes(pcm), 2, 1, 24000, 16000, None)
        return audio


async def worker(arm, input_path):
    options = {}
    if arm == "pipecat":
        from experiments.pipecat.pipeline import run_pipeline
        options["turn_handler"] = run_pipeline

    credential = Path(os.environ["CREDENTIALS_DIRECTORY"])
    token = (credential / "voice-device-token").read_text().strip()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(credential / "voice-cert", credential / "voice-key")
    trust = ssl.create_default_context(cafile=str(credential / "voice-ca"))
    audio = input_path.read_bytes()
    # Include the endpoint delay in the paced input for both arms.
    audio += bytes(48000)
    async with http_client() as http:
        provider = DashScope.from_environment(http)
        if not matches_config(provider):
            print(json.dumps({"preflight": "configuration_mismatch"}))
            return
        print(json.dumps({"preflight": "ok", "rss_kib": rss_kib()}))
        for line in sys.stdin:
            if line.strip() != "turn":
                break
            turn = str(uuid4())
            before = resource.getrusage(resource.RUSAGE_SELF)
            output = io.StringIO()
            result = "setup_failed"
            try:
                with redirect_stdout(output):
                    async with voice_server("127.0.0.1", PORT, tls, token, provider,
                                            GreetingPolicy(), timings=True, **options):
                        try:
                            async with asyncio.timeout(55):
                                result = await trial(audio, token, trust, turn)
                        except ConnectionClosed as error:
                            result = f"ws_{error.code}"
                        except TimeoutError:
                            result = "client_timeout"
                        except Exception:
                            result = "client_error"
            except OSError:
                pass
            after = resource.getrusage(resource.RUSAGE_SELF)
            print(json.dumps({
                "arm": arm, "turn_id": turn, "result": result,
                **timings(output.getvalue(), turn),
                "cpu_ms": round(1000 * (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)),
                "process_peak_kib": after.ru_maxrss, "rss_after_cleanup_kib": rss_kib(),
            }))


async def response(process, seconds):
    async with asyncio.timeout(seconds):
        line = await process.stdout.readline()
    return json.loads(line)


async def compare(audio, inherited_fds=()):
    root = Path.cwd()
    data = audio.read_bytes()
    size = len(data)
    if not 0 < size <= 320000 or size % 2:
        raise ValueError("expected up to ten seconds of mono PCM s16le at 16 kHz")
    processes = {}
    rows = []
    try:
        for arm, cwd in (("baseline", root / "baseline"), ("pipecat", root)):
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-B", "-m", "experiments.pipecat.ab", arm, str(audio),
                cwd=cwd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, pass_fds=inherited_fds,
            )
            processes[arm] = process
            status = await response(process, 20)
            print(json.dumps({"arm": arm, **status}))
            if status["preflight"] != "ok":
                return

        print(json.dumps({"region": "cn-beijing", "models_and_voice": EXPECTED,
                          "endpoint_ms": 1500, "max_attempts": ROUNDS * 2}))
        for index in range(ROUNDS):
            order = tuple(processes) if index % 2 == 0 else tuple(reversed(processes))
            for arm in order:
                process = processes[arm]
                process.stdin.write(b"turn\n")
                await process.stdin.drain()
                row = await response(process, 65)
                row.update(round=index + 1, cold=index == 0)
                rows.append(row)
                print(json.dumps(row))
            if index == 0 and all(row["result"] == "ws_4402" for row in rows):
                break  # Identical source rejected by both greeting gates.
    finally:
        for process in processes.values():
            process.stdin.close()
        for process in processes.values():
            try:
                async with asyncio.timeout(5):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()

    for arm in processes:
        arm_rows = [row for row in rows if row["arm"] == arm]
        ok = [row for row in arm_rows if row["result"] == "ok"]
        steady = [row for row in ok if not row["cold"]]
        metrics = {}
        for key in set().union(*(row["deltas_ms"] for row in steady)):
            values = [row["deltas_ms"][key] for row in steady if key in row["deltas_ms"]]
            metrics[key] = {"n": len(values), "median": statistics.median(values),
                            "range": [min(values), max(values)]}
        print(json.dumps({"arm": arm, "attempts": len(arm_rows), "ok": len(ok),
                          "failed": len(arm_rows) - len(ok), "steady_ms": metrics}))


async def compare_seed():
    print(json.dumps({"input": "cosyvoice_seed", "seed_tts_attempt": 1}))
    audio = await seed_audio()
    with os.fdopen(os.memfd_create("pipecat-synthetic-input"), "wb") as buffer:
        buffer.write(audio)
        buffer.flush()
        await compare(Path(f"/proc/self/fd/{buffer.fileno()}"), (buffer.fileno(),))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3:
            asyncio.run(worker(sys.argv[1], Path(sys.argv[2])))
        elif sys.argv[1:] == ["--seed"]:
            asyncio.run(compare_seed())
        else:
            asyncio.run(compare(Path.cwd() / "input.pcm"))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        sys.exit(1)
