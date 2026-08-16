"""Microsoft Edge TTS backend (via the free edge-tts package, no API key)."""

import asyncio

import edge_tts

# Default voice per language code. Add more as you need other languages;
# run `edge-tts --list-voices` to browse what's available.
LANG_VOICES = {
    "ro": "ro-RO-EmilNeural",
    "en": "en-US-AriaNeural",
    "uk": "uk-UA-PolinaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "pl": "pl-PL-ZofiaNeural",
    "pt": "pt-BR-FranciscaNeural",
}


def synthesize(text: str, voice: str, speed: float, out_path: str) -> None:
    """speed is a multiplier: 1.0 normal, 0.8 = 20% slower, 1.2 = 20% faster."""
    pct = round((speed - 1.0) * 100)
    rate = f"{'+' if pct >= 0 else ''}{pct}%"

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(out_path)

    asyncio.run(_run())
