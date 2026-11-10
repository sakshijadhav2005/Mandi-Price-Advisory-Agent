"""Voice evaluation (plan section 10): WER, CER and intent accuracy per language.

Input is a CSV manifest (see evaluation/test_sets/voice_manifest.example.csv):

    id,language,audio_path,reference,expected_crop,hypothesis

- `reference` is what the speaker actually said (typed by a native speaker).
- `expected_crop` is the crop the question is about ("" if none).
- `hypothesis` is optional: a transcript already captured elsewhere (for example
  by the browser recogniser during the pilot). When it is empty, the audio file
  is transcribed with the server STT provider (STT_PROVIDER=whisper).

Intent accuracy = the transcript still lets the agent find the right crop, which
is what decides whether the farmer gets a useful answer.

Usage (from the repo root):
    python evaluation/scripts/voice_eval.py evaluation/test_sets/voice_manifest.csv
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.reference import detect_crop  # noqa: E402
from app.voice import adapters  # noqa: E402
from app.voice.metrics import cer, wer  # noqa: E402

REPORT = ROOT / "evaluation" / "reports" / "voice_results.md"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    args = ap.parse_args()
    rows = list(csv.DictReader(args.manifest.open(encoding="utf-8-sig")))
    per_lang: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    errors = []
    for row in rows:
        hyp = (row.get("hypothesis") or "").strip()
        if not hyp:
            audio_path = (args.manifest.parent / row["audio_path"]).resolve()
            try:
                tr = adapters.transcribe(audio_path.read_bytes(), suffix=audio_path.suffix, language_hint=row["language"])
                hyp = tr.text
            except (adapters.VoiceNotConfigured, OSError) as exc:
                errors.append(f"{row['id']}: {exc}")
                continue
        m = per_lang[row["language"]]
        m["wer"].append(wer(row["reference"], hyp))
        m["cer"].append(cer(row["reference"], hyp))
        m["intent"].append(float((detect_crop(hyp) or "") == (row.get("expected_crop") or "")))
    lines = ["# Voice evaluation", "", "| Language | n | WER | CER | Intent accuracy |", "|---|---|---|---|---|"]
    for lang, m in sorted(per_lang.items()):
        lines.append(
            f"| {lang} | {len(m['wer'])} | {100 * statistics.fmean(m['wer']):.1f}% | "
            f"{100 * statistics.fmean(m['cer']):.1f}% | {100 * statistics.fmean(m['intent']):.1f}% |"
        )
    if errors:
        lines += ["", f"Skipped {len(errors)} samples:", *[f"- {e}" for e in errors[:20]]]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
