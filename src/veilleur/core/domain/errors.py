# SPDX-License-Identifier: EUPL-1.2
"""Errors of the core, identified by stable codes.

The core never translates: it raises `VeilleurError` with a stable English code and named parameters, and the
applications turn them into translated messages (cahier EF-82). Codes are part of the HTTP interface (protocol
specification §9.2) and of the administration command line: they never change meaning.
"""

from __future__ import annotations

from typing import Any

# Request and API errors.
BAD_REQUEST = "bad_request"
NOT_FOUND = "not_found"
METHOD_NOT_ALLOWED = "method_not_allowed"
REVOKED = "revoked"
COLLECTOR_NOT_ALLOWED = "collector_not_allowed"
UNKNOWN_COLLECTOR = "unknown_collector"
UNKNOWN_FILTER = "unknown_filter"
UNKNOWN_RENDERER = "unknown_renderer"
INVALID_SUBSCRIPTION = "invalid_subscription"
INVALID_PARAMS = "invalid_params"
TEAM_SUBSCRIPTION = "team_subscription"
VERSION_CONFLICT = "version_conflict"
SUBSCRIPTION_DELETED = "subscription_deleted"
PURGED = "purged"
BODY_TOO_LARGE = "body_too_large"
RATE_LIMITED = "rate_limited"
INTERNAL_ERROR = "internal_error"
# Administration.
UNKNOWN_PAIRING = "unknown_pairing"
AMBIGUOUS_PAIRING = "ambiguous_pairing"
UNKNOWN_SUBSCRIPTION = "unknown_subscription"
INVALID_LABEL = "invalid_label"
INVALID_CONFIG = "invalid_config"
# Collections (reported in the `sources` of a manifest, without detail).
COLLECTOR_FAILED = "collector_failed"
COLLECTOR_MISSING = "collector_missing"
BAD_ITEM = "bad_item"
NETWORK_UNAVAILABLE = "network_unavailable"
# Collections through the HTTP client (cahier ES-08) and the provided collectors; `http_<status>` for an HTTP error.
BAD_URL = "bad_url"
ADDRESS_REFUSED = "address_refused"
DNS_FAILED = "dns_failed"
NETWORK_ERROR = "network_error"
TIMEOUT = "timeout"
TOO_MANY_REDIRECTS = "too_many_redirects"
RESPONSE_TOO_LARGE = "response_too_large"
UNEXPECTED_CONTENT_TYPE = "unexpected_content_type"
BAD_RESPONSE = "bad_response"
ROBOTS_DISALLOWED = "robots_disallowed"
ROBOTS_UNAVAILABLE = "robots_unavailable"
HOST_QUOTA_EXCEEDED = "host_quota_exceeded"
SELECTOR_NO_MATCH = "selector_no_match"

CODES = frozenset(
    {
        BAD_REQUEST,
        NOT_FOUND,
        METHOD_NOT_ALLOWED,
        REVOKED,
        COLLECTOR_NOT_ALLOWED,
        UNKNOWN_COLLECTOR,
        UNKNOWN_FILTER,
        UNKNOWN_RENDERER,
        INVALID_SUBSCRIPTION,
        INVALID_PARAMS,
        TEAM_SUBSCRIPTION,
        VERSION_CONFLICT,
        SUBSCRIPTION_DELETED,
        PURGED,
        BODY_TOO_LARGE,
        RATE_LIMITED,
        INTERNAL_ERROR,
        UNKNOWN_PAIRING,
        AMBIGUOUS_PAIRING,
        UNKNOWN_SUBSCRIPTION,
        INVALID_LABEL,
        INVALID_CONFIG,
        COLLECTOR_FAILED,
        COLLECTOR_MISSING,
        BAD_ITEM,
        NETWORK_UNAVAILABLE,
        BAD_URL,
        ADDRESS_REFUSED,
        DNS_FAILED,
        NETWORK_ERROR,
        TIMEOUT,
        TOO_MANY_REDIRECTS,
        RESPONSE_TOO_LARGE,
        UNEXPECTED_CONTENT_TYPE,
        BAD_RESPONSE,
        ROBOTS_DISALLOWED,
        ROBOTS_UNAVAILABLE,
        HOST_QUOTA_EXCEEDED,
        SELECTOR_NO_MATCH,
    }
)


class VeilleurError(Exception):
    """A refusal or failure with a stable `code` and named parameters for its translated message.

    Parameters never hold a secret, a subscription parameter or a request body: they may be shown or logged.
    """

    def __init__(self, code: str, **params: Any) -> None:
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}")
        self.code = code
        self.params = params
        super().__init__(code if not params else f"{code} {params}")


class CollectorError(Exception):
    """Raised by a collector for a failure it can name with a stable code (for example `network_unavailable`).

    Any other exception raised by a collector is reported as `collector_failed`. Plugins may use their own codes:
    a code must match `[a-z][a-z0-9_]{0,63}` and never carries internal detail.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
