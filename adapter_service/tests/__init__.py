"""Shared unittest discovery setup for the adapter test suite."""

import os


# Keep production mock behavior disabled while making direct unittest discovery
# use the same explicit test-only provider mode as pytest's conftest.py.
os.environ.setdefault("AI_WPS_ENABLE_MOCK_PROVIDER", "1")
