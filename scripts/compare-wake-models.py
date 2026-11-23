"""Evaluate two fixed KWS candidates over development and separate synthetic validation inputs."""
import argparse
import hashlib
from pathlib import Path
import runpy

import numpy as np
import sherpa_onnx

SOURCE = runpy.run_path(str(Path(__file__).with_name("test-wake-model.py")))
phrase, silence = SOURCE["phrase"], SOURCE["silence"]


def development():
    for name, text, expected in (
        ("solo", "wa3 li4 wa3 li4", True),
        ("joined", "wa3 li4 wa3 li4 wan2 cai1 dong4 wu4", True),
        ("near-ma", "wa3 li4 ma3 li4", False),
        ("near-lai", "wa3 li4 wa3 lai2", False),
        ("single", "wa3 li4", False),
        ("command", "wan2 cai1 dong4 wu4", False),
    ):
        yield name, phrase(text), expected
    wake = phrase("wa3 li4 wa3 li4")
    command = phrase("wan2 cai1 dong4 wu4")
    for gap in (0, 120, 300, 750):
        yield f"gap-{gap}", np.concatenate((wake, silence(gap), command)), True


def validation():
    for name, text, speed, pitch, expected in (
        ("slow-solo", "wa3 li4 wa3 li4", 131, 43, True),
        ("fast-solo", "wa3 li4 wa3 li4", 177, 59, True),
        ("new-command", "wa3 li4 wa3 li4 wo3 xiang3 liao2 tian1", 168, 41, True),
        ("near-fa", "wa3 li4 fa3 li4", 161, 48, False),
        ("near-na", "wa3 li4 na3 li4", 166, 55, False),
        ("near-ni", "wa3 li4 wa3 ni4", 137, 61, False),
        ("different-word", "wo3 xiang3 kan4 xiong2 mao1", 165, 52, False),
        ("homophone", "wa3 li4 wa3 li4", 143, 69, None),
    ):
        yield name, phrase(text, speed, pitch), expected
    speech = phrase("wa3 li4 wa3 li4", 158, 63).astype("float64")
    rng = np.random.default_rng(5013)
    noise = rng.normal(0, np.sqrt(np.mean(speech ** 2)) / 4, len(speech))
    yield "wake-plus-noise", (speech + noise).round().clip(-32768, 32767).astype("<i2"), True
    yield "noise-alone", rng.integers(-500, 500, 32000, dtype=np.int16), False


def inspect(model, suite, cases):
    tp = positive = tn = negative = 0
    for name, body, expected in cases:
        pcm = np.concatenate((silence(500), body, silence(2000)))
        stream = model.create_stream()
        hits = []
        for start in range(0, len(pcm), 320):
            stream.accept_waveform(16000, pcm[start:start + 320].astype("float32") / 32768)
            while model.is_ready(stream):
                model.decode_stream(stream)
                result = model.keyword_spotter.get_result(stream)
                if result.keyword:
                    hits.append(start + 320)
                    model.reset_stream(stream)
        if expected is True:
            positive += 1
            tp += len(hits) == 1
        if expected is False:
            negative += 1
            tn += not hits
        print(f"{suite} {name} expected={expected} hits={hits} sha={hashlib.sha256(pcm.tobytes()).hexdigest()}")
    print(f"{suite} positive={tp}/{positive} negative={tn}/{negative}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wenetspeech", type=Path)
    args = parser.parse_args()
    assets = SOURCE["ASSETS"]
    wenet = args.wenetspeech
    for name, folder, epoch in (("zh-en", assets, 13), ("wenetspeech", wenet, 12)):
        paths = {
            part: str(folder / f"{part}-epoch-{epoch}-avg-2-chunk-16-left-64"
                               f"{'.int8' if epoch == 12 or part != 'decoder' else ''}.onnx")
            for part in ("encoder", "decoder", "joiner")
        }
        model = sherpa_onnx.KeywordSpotter(
            **paths, tokens=str(folder / "tokens.txt"), keywords_file=str(assets / "keywords.txt"),
            keywords_score=1.5, keywords_threshold=0.25, num_trailing_blanks=2, num_threads=1,
        )
        print(name)
        inspect(model, "development", development())
        inspect(model, "validation", validation())


if __name__ == "__main__":
    main()
