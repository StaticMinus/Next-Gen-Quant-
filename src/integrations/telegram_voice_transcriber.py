"""
src/integrations/telegram_voice_transcriber.py
─────────────────────────────────────────────────────────────────────────────
Voice Note Intelligence Engine for AgentQuant Telegram Bot.
Downloads incoming Telegram voice/audio messages, converts .oga/.ogg to 16kHz WAV
via FFmpeg, and transcribes speech to text using Google Speech API.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

import requests

try:
    import speech_recognition as sr
except ImportError:
    sr = None

logger = logging.getLogger("voice_transcriber")

TEMP_DIR = Path("cache/voice_temp")


def transcribe_telegram_voice(file_id: str, bot_token: str) -> Optional[str]:
    """
    Downloads a voice message from Telegram Bot API, converts to WAV via FFmpeg,
    and returns the transcribed text. Returns None if transcription fails.
    """
    if not file_id or not bot_token:
        return None
    if sr is None:
        logger.warning("speech_recognition not installed. Voice transcription unavailable.")
        return None

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    oga_path = TEMP_DIR / f"{file_id}.oga"
    wav_path = TEMP_DIR / f"{file_id}.wav"

    try:
        # 1. Fetch file_path from Telegram API
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        resp = requests.get(get_file_url, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Telegram getFile failed: {data}")
            return None

        remote_path = data["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{remote_path}"

        # 2. Download audio file
        audio_resp = requests.get(download_url, timeout=20)
        if audio_resp.status_code != 200:
            logger.error(f"Failed to download voice file: status {audio_resp.status_code}")
            return None

        oga_path.write_bytes(audio_resp.content)

        # 3. Convert to 16kHz mono WAV using FFmpeg
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(oga_path),
            "-ar", "16000",
            "-ac", "1",
            str(wav_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg conversion error: {result.stderr}")
            return None

        # 4. Transcribe using SpeechRecognition (Google Free tier)
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            logger.info(f"Successfully transcribed voice: '{text}'")
            return text

    except Exception as e:
        if sr and isinstance(e, sr.UnknownValueError):
            logger.info("Speech recognition could not understand audio (inaudible or silence).")
        elif sr and isinstance(e, sr.RequestError):
            logger.error(f"Speech recognition service error: {e}")
        else:
            logger.error(f"Unexpected error in voice transcription: {e}")
        return None
    finally:
        # Cleanup temporary files
        try:
            if oga_path.exists():
                oga_path.unlink()
            if wav_path.exists():
                wav_path.unlink()
        except Exception:
            pass
