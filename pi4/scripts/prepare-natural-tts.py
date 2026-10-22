#!/usr/bin/env python3
"""Optional setup-only online synthesis; no voice service needed during alarms.

Use an isolated venv with edge-tts==7.3.1 and a system ffmpeg.
Only the fixed, non-personal alarm sentence is sent to the online service.
"""
import argparse
import asyncio
from pathlib import Path
import subprocess
import tempfile


async def prepare(output: Path, voice: str) -> None:
    import edge_tts

    if output.exists():
        raise FileExistsError(f"Refusing to replace existing audio: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fall-tts-", dir=output.parent) as directory:
        mp3 = Path(directory) / "speech.mp3"
        wav = Path(directory) / "speech.wav"
        await edge_tts.Communicate("낙상이 감지되었습니다.", voice, rate="-5%").save(str(mp3))
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1",
                        "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
        # Fail rather than overwrite if another invocation created the file.
        import os
        os.link(wav, output)
    print(f"Prepared {output} ({voice}); runtime playback is offline")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voice", default="ko-KR-SunHiNeural")
    args = parser.parse_args()
    asyncio.run(prepare(args.output, args.voice))
