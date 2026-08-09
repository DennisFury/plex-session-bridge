"""
Example Apple TV inventory.

The bridge uses config.yaml, not this file, for runtime configuration. This file
exists only as a migration/reference aid for users who already keep Apple TV
details in Python dictionaries.
"""

APPLE_TV_DEVICES = {
    "media_room": {
        "name": "media_room",
        "dns_name": "media-room-atv",
        "ip_address": "192.0.2.21",
        "mac_address": "A1B2C3D4E5F6",
        "short_name": "media",
    },
    "bedroom": {
        "name": "bedroom",
        "dns_name": "bedroom-atv",
        "ip_address": "192.0.2.22",
        "mac_address": "B2C3D4E5F6A1",
        "short_name": "bed",
    },
    "office": {
        "name": "office",
        "dns_name": "office-atv",
        "ip_address": "192.0.2.23",
        "mac_address": "C3D4E5F6A1B2",
        "short_name": "office",
    },
}
