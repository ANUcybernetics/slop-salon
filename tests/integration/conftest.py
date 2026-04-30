"""Shared fixtures for live integration tests.

Each fixture skips automatically if its required env vars are missing,
so partial credential coverage is fine.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def bsky_live_creds():
    """Real Bluesky credentials. Skips if not provided."""
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not (handle and password):
        pytest.skip("BSKY_HANDLE and BSKY_PASSWORD env vars required for live Bluesky tests")
    return handle, password
