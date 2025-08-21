import uuid


class RequestIDMiddleware:
    header_name = "HTTP_X_REQUEST_ID"  # incoming
    response_header_name = "X-Request-ID"  # outgoing

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, django_request):
        request_id = django_request.META.get(self.header_name) or str(uuid.uuid4())
        django_request.request_id = request_id
        response = self.get_response(django_request)
        response[self.response_header_name] = request_id
        return response
