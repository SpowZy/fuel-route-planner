from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler


def handle(exc, context):
    """One error shape for every failure: {"error": {"code", "message", ...}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, ValidationError):
        response.data = {
            "error": {
                "code": "invalid_request",
                "message": "Invalid request parameters",
                "fields": response.data,
            }
        }
    else:
        response.data = {
            "error": {"code": getattr(exc, "default_code", "error"), "message": str(exc.detail)}
        }
    return response
