from django.conf import settings
from django.http import HttpResponse


class ApiCorsMiddleware:
    """Apply CORS only to an explicitly configured browser origin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if request.path.startswith("/api/"):
            origin = request.headers.get("Origin")
            if origin and origin in settings.CORS_ALLOWED_ORIGINS:
                response["Access-Control-Allow-Origin"] = origin
                response["Vary"] = "Origin"
                response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
        return response
