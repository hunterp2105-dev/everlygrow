"""Shared retry-worthiness check for external API failures (Blotato,
Anthropic) — used by both app/lib/approval.py (publish failures) and
app/lib/guardrails.py (guardrail-engine failures). Extracted after finding
the same 4xx-vs-5xx distinction was needed in both places but only
actually existed in one (approval.py) — see the calling code's history for
the concrete case that surfaced this (a permanent 400 was being retried 3
times before this existed).
"""


def is_retryable_http_error(exc: Exception) -> bool:
    """4xx (except 429) means the request itself was malformed — retrying
    the identical request fails identically every time and just burns
    retries for nothing. 429 and 5xx are worth retrying; anything without
    an HTTP response (network errors, timeouts) defaults to retryable."""
    response = getattr(exc, "response", None)
    if response is None:
        return True
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        return True
    return status_code == 429 or status_code >= 500
