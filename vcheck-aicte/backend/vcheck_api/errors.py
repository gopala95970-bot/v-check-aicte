from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def bad_request(msg, code="bad_request", **d): return ApiError(400, code, msg, d)
def unauthorized(msg="Sign in to continue.", code="unauthorized"): return ApiError(401, code, msg)
def forbidden(msg="You do not have permission to do that.", code="forbidden"): return ApiError(403, code, msg)
def not_found(msg="That item could not be found.", code="not_found"): return ApiError(404, code, msg)
def conflict(msg, code="conflict", **d): return ApiError(409, code, msg, d)
def too_large(msg="The upload is too large."): return ApiError(413, "payload_too_large", msg)
def unprocessable(msg, code="validation_error", **d): return ApiError(422, code, msg, d)
def too_many(msg, retry_after: int): return ApiError(429, "too_many_attempts", msg, {"retry_after_seconds": retry_after})
