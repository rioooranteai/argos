class ExtractionError(Exception):
    """Base exception for every extraction error."""
    pass


class UnsupportedProviderError(ExtractionError):
    """The requested provider is not available."""
    pass


class ExtractionAgentError(ExtractionError):
    """Failed while running the extraction agent."""
    pass