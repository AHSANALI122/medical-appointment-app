class MedBookError(Exception):
    """Base class for all application errors that map to a structured API response."""

    error_code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str | None = None):
        self.message = message or self.__class__.__name__
        super().__init__(self.message)


class SlotUnavailableError(MedBookError):
    error_code = "slot_unavailable"
    status_code = 409


class BookingConflictError(MedBookError):
    error_code = "booking_conflict"
    status_code = 409


class PolicyViolationError(MedBookError):
    error_code = "policy_violation"
    status_code = 422


class LLMProviderError(MedBookError):
    error_code = "llm_provider_error"
    status_code = 503


class NotFoundError(MedBookError):
    error_code = "not_found"
    status_code = 404


class UnauthorizedError(MedBookError):
    error_code = "unauthorized"
    status_code = 401


class ForbiddenError(MedBookError):
    error_code = "forbidden"
    status_code = 403


class ValidationAppError(MedBookError):
    error_code = "validation_error"
    status_code = 422


class RateLimitExceededError(MedBookError):
    error_code = "rate_limit_exceeded"
    status_code = 429
