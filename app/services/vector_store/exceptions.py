class VectorStoreError(Exception):
    """Base exception untuk semua error vector store."""
    pass


class UnsupportedProviderError(VectorStoreError):
    """Provider yang diminta tidak tersedia."""
    pass


class VectorStoreInsertError(VectorStoreError):
    """Gagal menyimpan data ke vector store."""
    pass


class VectorStoreSearchError(VectorStoreError):
    """Gagal melakukan pencarian di vector store."""
    pass