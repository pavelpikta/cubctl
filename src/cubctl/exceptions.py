"""CUB API exceptions."""


class CubApiError(Exception):
    """Raised when the CUB API returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}
