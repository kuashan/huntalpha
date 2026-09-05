from django.http import HttpResponse


class ApiCorsMiddleware:
    """Development-only CORS bridge for the Vue dev server and Django session."""

    allowed_origin = "http://127.0.0.1:5173"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Access-Control-Allow-Origin"] = self.allowed_origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-CSRFToken"
        return response
