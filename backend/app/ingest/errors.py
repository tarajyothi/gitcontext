class IngestError(Exception):
    """Expected, user-facing ingestion failure."""
    def __init__(self, code: str, message: str, status: int = 400, headers: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.headers = code, message, status, headers
