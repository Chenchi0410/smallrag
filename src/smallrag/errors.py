class SmallRAGError(Exception):
    """Base class for errors that can safely be exposed through the API."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ConfigurationError(SmallRAGError):
    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message, 503)


class UpstreamError(SmallRAGError):
    def __init__(self, service: str, message: str) -> None:
        super().__init__(f"{service}_upstream_error", message, 502)

