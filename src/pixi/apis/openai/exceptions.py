class APIError(Exception):
    def __init__(self, message: str = "", code: str | None = None):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(APIError):
    pass


class APIConnectionError(APIError):
    pass
