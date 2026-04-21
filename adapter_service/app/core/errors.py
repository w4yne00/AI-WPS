class AdapterError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AdapterUnavailableError(AdapterError):
    def __init__(self, message: str = "Local adapter service is unavailable.") -> None:
        super().__init__("ADAPTER_UNAVAILABLE", message, status_code=503)


class DifyTimeoutError(AdapterError):
    def __init__(self, message: str = "Dify request timed out.") -> None:
        super().__init__("DIFY_TIMEOUT", message, status_code=504)


class DifyAuthError(AdapterError):
    def __init__(self, message: str = "Dify authentication failed.") -> None:
        super().__init__("DIFY_AUTH_FAILED", message, status_code=401)


class DifyUnavailableError(AdapterError):
    def __init__(self, message: str = "Dify endpoint is unreachable.") -> None:
        super().__init__("DIFY_UNREACHABLE", message, status_code=502)

