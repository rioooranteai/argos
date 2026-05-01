from abc import ABC, abstractmethod

from app.services.voice.exceptions import UnsupportedFormatError
from app.services.voice.model import TTSRequest, TTSResult


class BaseTTSProvider(ABC):
    """
    Kontrak wajib untuk semua TTS provider.

    Setiap provider yang inherit class ini WAJIB mengimplementasikan
    semua abstract method/property di bawah. Jika tidak, Python akan
    raise TypeError saat provider di-instantiate.

    Cara tambah provider baru:
        1. Buat file baru di providers/
        2. Inherit BaseTTSProvider
        3. Implement semua method di bawah
        4. Register ke TTSFactory
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Identifier unik provider.
        Contoh: 'openai', 'google', 'elevenlabs'
        """
        ...

    @property
    @abstractmethod
    def supported_voices(self) -> list[str]:
        """
        Daftar nama voice yang bisa digunakan.
        Contoh: ['alloy', 'echo', 'nova']
        """
        ...

    @property
    @abstractmethod
    def supported_formats(self) -> list[str]:
        """
        Daftar format audio output yang didukung.
        Contoh: ['mp3', 'wav', 'opus']
        """
        ...

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        """
        Convert teks ke audio bytes.

        Args:
            request: TTSRequest berisi text, voice, format, speed

        Returns:
            TTSResult berisi audio_bytes, format, character_count, provider

        Raises:
            TTSError: jika proses gagal
            UnsupportedFormatError: jika format tidak didukung
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verifikasi apakah provider siap digunakan.

        Untuk provider berbasis API  : cek konektivitas & validitas API key
        Untuk provider model lokal   : cek apakah model sudah ter-load

        Returns:
            True jika provider sehat, False jika tidak
        """
        ...

    def validate_format(self, fmt: str) -> None:
        """Helper validasi format — bisa dipakai langsung di semua provider."""
        if fmt not in self.supported_formats:
            raise UnsupportedFormatError(fmt, self.provider_name, self.supported_formats)

    def validate_voice(self, voice: str) -> None:
        """Helper validasi voice — bisa dipakai langsung di semua provider."""
        if voice not in self.supported_voices:
            raise ValueError(
                f"Voice '{voice}' tidak didukung oleh {self.provider_name}. "
                f"Tersedia: {', '.join(self.supported_voices)}"
            )
