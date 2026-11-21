from enum import Enum

from pydantic import BaseModel, Field


class VoiceType(str, Enum):
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SHIMMER = "shimmer"


class AudioFormat(str, Enum):
    MP3 = "mp3"
    WAV = "wav"
    OPUS = "opus"
    FLAC = "flac"
    AAC = "aac"
    PCM = "pcm"


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: VoiceType = VoiceType.ALLOY
    format: AudioFormat = AudioFormat.MP3
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class TTSResult(BaseModel):
    audio_bytes: bytes
    format: str
    character_count: int
    provider: str


class STTRequest(BaseModel):
    language: str = Field(default="id", description="ISO 639-1 language code, e.g. 'id', 'en'")
    prompt: str | None = Field(default=None, description="Context hint to improve accuracy")
    audio_format: str = Field(default="webm", description="Audio format: wav, webm, mp3, etc.")
    with_timestamps: bool = False


class STTSegment(BaseModel):
    start: float
    end: float
    text: str


class STTResult(BaseModel):
    text: str
    language: str | None = None
    language_probability: float | None = None
    segments: list[STTSegment] = []
    provider: str
