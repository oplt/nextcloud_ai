class NextcloudError(Exception):
    """Base exception for Nextcloud integration failures."""


class NextcloudAuthenticationError(NextcloudError):
    """Raised when the technical account cannot authenticate against Nextcloud."""


class NextcloudAPIError(NextcloudError):
    """Raised when a remote API call fails."""


class BridgeTokenError(NextcloudError):
    """Raised when a bridge token is missing, expired, invalid, or replayed."""
