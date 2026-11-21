class VectorStoreError(Exception):
    """Base exception for every vector store error."""
    pass


class UnsupportedProviderError(VectorStoreError):
    """The requested provider is not available."""
    pass


class VectorStoreInsertError(VectorStoreError):
    """Failed to store data in the vector store."""
    pass


class VectorStoreSearchError(VectorStoreError):
    """Failed to search the vector store."""
    pass