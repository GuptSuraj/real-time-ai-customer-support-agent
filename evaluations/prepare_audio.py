"""Generate optional scripted USER audio. This is not part of the production voice pipeline."""

import argparse
import json
import os
import wave
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="evaluations/scenarios.json")
    parser.add_argument(
        "--tts-model", required=True, help="Explicit Google TTS model; incurs provider charges"
    )
    parser.add_argument("--scenario", help="Generate only this scenario ID")
    args = parser.parse_args()
    load_dotenv()
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("Set GOOGLE_API_KEY in .env before generating audio")
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    manifest = Path(args.manifest)
    for scenario in json.loads(manifest.read_text()):
        if args.scenario and scenario["id"] != args.scenario:
            continue
        for turn in scenario["turns"]:
            target = manifest.parent / turn["audio"]
            if target.exists():
                continue
            response = client.models.generate_content(
                model=args.tts_model,
                contents=turn["text"],
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                        )
                    ),
                ),
            )
            parts = response.candidates[0].content.parts if response.candidates else []
            audio = b"".join(p.inline_data.data for p in parts if p.inline_data and p.inline_data.data)
            if not audio:
                raise RuntimeError(f"No audio returned for {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if audio.startswith(b"RIFF"):
                target.write_bytes(audio)
            else:
                with wave.open(str(target), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(24000)
                    output.writeframes(audio)
            print(target)
    client.close()


if __name__ == "__main__":
    main()
