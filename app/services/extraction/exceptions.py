class ExtractionError(Exception):
    """Base exception untuk semua error extraction."""
    pass


class UnsupportedProviderError(ExtractionError):
    """Provider yang diminta tidak tersedia."""
    pass


class ExtractionAgentError(ExtractionError):
    """Gagal saat menjalankan agent ekstraksi."""
    pass