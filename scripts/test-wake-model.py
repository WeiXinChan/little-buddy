"""Replay fixed synthetic Mandarin cases on the same ONNX graphs as Android."""
import argparse
import hashlib
import subprocess
from pathlib import Path

import numpy as np
import sherpa_onnx

ASSETS = Path(__file__).resolve().parents[1] / "app/src/main/assets/wake"


def phrase(text):
    wav = subprocess.check_output(["espeak-ng", "-v", "cmn-latn-pinyin", "-s", "150", "-p", "50",
                                   "-a", "100", "--stdout", text])
    pcm = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
                                   "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"], input=wav)
    samples = np.frombuffer(pcm, dtype="<i2")
    audible = np.flatnonzero(np.abs(samples.astype("int32")) > 327)
    return samples[audible[0]:audible[-1] + 1]


def silence(ms):
    return np.zeros(16 * ms, dtype="<i2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, help="write PCM and hit indices for the JVM stream replay")
    args = parser.parse_args()
    if args.fixtures:
        args.fixtures.mkdir(parents=True, exist_ok=True)
    spotter = sherpa_onnx.KeywordSpotter(
        **{part: str(next(ASSETS.glob(f"{part}-*.onnx"))) for part in ("encoder", "decoder", "joiner")},
        tokens=str(ASSETS / "tokens.txt"), keywords_file=str(ASSETS / "keywords.txt"),
        keywords_score=1.5, num_trailing_blanks=2, num_threads=1,
    )
    wake = phrase("wa3 li4 wa3 li4")
    command = phrase("wan2 cai1 dong4 wu4")
    cases = {"wake": (wake, True), "joined": (phrase("wa3 li4 wa3 li4 wan2 cai1 dong4 wu4"), True)}
    for gap in (0, 120, 300, 750):
        cases[f"gap-{gap}"] = (np.concatenate((wake, silence(gap), command)), True)
    for name, text in (
        ("single-syllable-pair", "wa3 li4"),
        ("near-wa-li-ma-li", "wa3 li4 ma3 li4"),
        ("command-alone", "wan2 cai1 dong4 wu4"),
        ("near-wa-li-wa-lai", "wa3 li4 wa3 lai2"),
    ):
        cases[name] = (phrase(text), False)
    cases["noise"] = (np.random.default_rng(49).integers(-250, 250, 48000, dtype=np.int16), False)
    rng = np.random.default_rng(4202)
    rms = np.sqrt(np.mean(wake.astype("float64") ** 2))
    for db in (10, 20):
        mixed = wake + rng.standard_normal(len(wake)) * (rms / (10 ** (db / 20)))
        cases[f"wake-noise-{db}db"] = (mixed.round().clip(-32768, 32767).astype("<i2"), True)
    failures = []
    for name, (body, expected) in cases.items():
        pcm = np.concatenate((silence(500), body, silence(2000)))
        stream = spotter.create_stream()
        matches = []
        for cursor in range(0, len(pcm), 320):
            stream.accept_waveform(16000, pcm[cursor:cursor + 320].astype("float32") / 32768)
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
                hit = spotter.keyword_spotter.get_result(stream)
                if hit.keyword:
                    matches.append((min(len(pcm), cursor + 320), hit.timestamps))
                    spotter.reset_stream(stream)
        print(f"{name} samples={len(pcm)} sha256={hashlib.sha256(pcm.tobytes()).hexdigest()} hits={matches}")
        if args.fixtures:
            (args.fixtures / f"{name}.pcm").write_bytes(pcm.tobytes())
            hit_file = args.fixtures / f"{name}.hit"
            if matches:
                cursor, timestamps = matches[0]
                hit_file.write_text(
                    f"{cursor} {int((timestamps[-1] + 0.12) * 16000)}\n", encoding="ascii",
                )
            else:
                hit_file.unlink(missing_ok=True)
        if len(matches) != int(expected):
            failures.append(name)
    if failures:
        raise SystemExit("Unexpected model results: " + ", ".join(failures))


if __name__ == "__main__":
    main()
