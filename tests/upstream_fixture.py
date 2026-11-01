"""Real HTTPX streaming API with an entirely in-memory transport."""
import httpx

_ASYNC_CLIENT = httpx.AsyncClient


def mock_upstream(response=None, *, error=None):
    requests = []
    async def handle(request):
        requests.append(request)
        if error is not None:
            raise error
        return httpx.Response(response.status_code, headers=response.headers,
                              stream=httpx.ByteStream(response.content))
    client = _ASYNC_CLIENT(transport=httpx.MockTransport(handle))
    client.requests_seen = requests
    return client
