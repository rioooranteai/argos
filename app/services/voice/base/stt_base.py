from abc import ABC, abstractmethod

from app.services.voice.exceptions import UnsupportedFormatError
from app.services.voice.exceptions import UnsupportedLanguageError
from app.services.voice.model import STTRequest, STTResult


class BaseSTTProvider(ABC):
    """
    Kontrak wajib untuk semua STT provider.

    Setiap provider yang inherit class ini WAJIB mengimplementasikan
    semua abstract method/property di bawah. Jika tidak, Python akan
    raise TypeError saat provider di-instantiate.

    Cara tambah provider baru:
        1. Buat file baru di providers/
        2. Inherit BaseSTTProvider
        3. Implement semua method di bawah
        4. Register ke STTFactory
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Identifier unik provider.
        Contoh: 'whisper', 'google', 'deepgram', 'azure'
        """
        ...

    @property
    @abstractmethod
    def supported_languages(self) -> list[str]:
        """
        Daftar kode bahasa ISO 639-1 yang didukung.
        Contoh: ['id', 'en', 'zh', 'ja']
        Kembalikan ['*'] jika provider mendukung semua bahasa.
        """
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """
        Daftar format audio input yang diterima.
        Contoh: ['mp3', 'wav', 'ogg', 'flac', 'webm']
        """
        ...

    @abstractmethod
    async def transcribe(
            self,
            audio_bytes: bytes,
            request: STTRequest,
    ) -> STTResult:
        """
        Convert audio bytes ke teks.

        Args:
            audio_bytes : Raw bytes dari file audio
            filename    : Nama file asli (dipakai untuk deteksi ekstensi)
            request     : STTRequest berisi language, prompt, with_timestamps

        Returns:
            STTResult berisi text, language, probability, segments, provider

        Raises:
            STTError: jika proses transkripsi gagal
            UnsupportedLanguageError: jika bahasa tidak didukung
            UnsupportedFormatError: jika format tidak didukung
        """
        ...


    def validate_language(self, language: str) -> None:
        """Helper validasi bahasa — bisa dipakai langsung di semua provider."""
        supported = self.supported_languages
        if supported == ["*"]:
            return
        if language not in supported:
            raise UnsupportedLanguageError(language, self.provider_name, supported)

    def validate_format(self, fmt: str) -> None:
        """Helper validasi format — bisa dipakai langsung di semua provider."""
        if fmt not in self.supported_formats:
            raise UnsupportedFormatError(fmt, self.provider_name, self.supported_formats)
