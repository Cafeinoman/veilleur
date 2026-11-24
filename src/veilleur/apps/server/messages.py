# SPDX-License-Identifier: EUPL-1.2
"""Translated messages for the stable codes of the core and of the protocol (spec EF-80 to EF-82).

The texts are marked with `N_` for extraction and translated when shown, in the language of the process (command
line) or of the request (HTTP interface).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from veilleur import i18n


def N_(message: str) -> str:
    """Mark a string for extraction without translating it."""
    return message


ERRORS: dict[str, str] = {
    # HTTP interface.
    "bad_request": N_("The request is malformed."),
    "not_found": N_("Nothing here."),
    "revoked": N_("This pairing has been revoked."),
    "collector_not_allowed": N_("Collector {name} is not allowed for this pairing."),
    "unknown_collector": N_("Unknown collector: {name}."),
    "unknown_filter": N_("Unknown filter: {name}."),
    "unknown_renderer": N_("Unknown rendering: {name}."),
    "invalid_subscription": N_("Invalid subscription document (member {member})."),
    "invalid_params": N_("Invalid parameters at {path} (rule {keyword})."),
    "team_subscription": N_("A team subscription is managed by the administrator."),
    "version_conflict": N_("The subscription has changed: its current version is {version}."),
    "subscription_deleted": N_("This subscription was deleted; create a new one."),
    "purged": N_("This package is no longer kept; ask for a state."),
    "body_too_large": N_("The request body is over {limit} bytes."),
    "rate_limited": N_("Too many requests; try again later."),
    "internal_error": N_("Internal error."),
    # Administration.
    "unknown_pairing": N_("No pairing matches {reference}."),
    "ambiguous_pairing": N_("Several pairings match {reference}; use its key_id."),
    "unknown_subscription": N_("No subscription matches {reference}."),
    "invalid_label": N_("A label is 1 to {max} printable characters: a marker such as “desk 3”, never a name."),
    "invalid_config": N_("Invalid configuration: {member}."),
    # Protocol (specification §11).
    "bad_authorization": N_("Missing or invalid authentication."),
    "bad_date": N_("Missing or malformed X-Veilleur-Date header."),
    "stale_date": N_("The request date is more than 5 minutes away from the server's clock."),
    "bad_envelope": N_("The body is not a sealed document."),
    "unsupported_version": N_("Unsupported protocol version."),
    "uid_mismatch": N_("The sealed document belongs to another subscription."),
    "kind_mismatch": N_("The sealed document is not a subscription document."),
    "decryption_failed": N_("The sealed document could not be opened."),
    "too_large": N_("The sealed document is too large."),
    "bad_subscription": N_("The subscription document is not a JSON object."),
}

SOURCE_ERRORS: dict[str, str] = {
    "collector_failed": N_("the collector failed"),
    "collector_missing": N_("the collector is not installed"),
    "bad_item": N_("some items were invalid"),
    "network_unavailable": N_("the network is unavailable"),
    "invalid_params": N_("invalid parameters"),
    "bad_url": N_("the address is not a valid http or https address"),
    "address_refused": N_("the address leads to a private or reserved network"),
    "dns_failed": N_("the host name could not be resolved"),
    "network_error": N_("the connection failed"),
    "timeout": N_("the source took too long to answer"),
    "too_many_redirects": N_("too many redirections"),
    "response_too_large": N_("the answer is too large"),
    "unexpected_content_type": N_("the answer is not of the expected type"),
    "bad_response": N_("the answer could not be read"),
    "robots_disallowed": N_("the site's robots.txt forbids this address"),
    "robots_unavailable": N_("the site's robots.txt could not be read"),
    "host_quota_exceeded": N_("too many requests to this host in one round"),
    "selector_no_match": N_("the CSS selector matches nothing on the page"),
    "bad_selector": N_("the CSS selector is not supported"),
}
HTTP_STATUS = N_("the source answered with HTTP status {status}")

EVENTS: dict[str, str] = {
    "pairing_created": N_("pairing {key_id} created"),
    "pairing_revoked": N_("pairing {key_id} revoked"),
    "subscription_created": N_("subscription {uid} created by pairing {key_id}"),
    "subscription_updated": N_("subscription {uid} of pairing {key_id} updated (version {version})"),
    "subscription_deleted": N_("subscription {uid} of pairing {key_id} deleted"),
    "team_synchronised": N_("team subscriptions: {created} created, {updated} updated, {deleted} deleted"),
    "team_pairing_skipped": N_("team subscription {name}: no pairing matches {reference}"),
    "round_finished": N_(
        "round: {collections} collections ({failed} failed), {reports} reports, {new_items} new items"
    ),
    "key_rotated": N_("server key replaced"),
}


def _format(template: str, params: Mapping[str, Any]) -> str:
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def error_message(code: str, params: Mapping[str, Any] | None = None, *, language: str | None = None) -> str:
    """Translated message of an error code, in `language` (default: the process's language)."""
    template = ERRORS.get(code, ERRORS["internal_error"])
    translated = i18n.translations(language).gettext(template) if language else i18n._(template)
    return _format(translated, params or {})


def event_message(code: str, params: Mapping[str, Any]) -> str:
    template = EVENTS.get(code)
    if template is None:
        return code
    return _format(i18n._(template), params)


def source_error(code: str) -> str:
    """A collection's error, translated; a plugin's own code is shown as is."""
    template = SOURCE_ERRORS.get(code)
    if template is None and code.startswith("http_") and code[5:].isdigit():
        return i18n._(HTTP_STATUS).format(status=code[5:])
    return code if template is None else i18n._(template)
