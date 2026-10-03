class ConnectorError(Exception):
    """Base class. Messages are written for an AI agent: say what happened and what to try."""


class AuthError(ConnectorError):
    pass


class NotFoundError(ConnectorError):
    pass


class RateLimitError(ConnectorError):
    pass


class ApiError(ConnectorError):
    pass