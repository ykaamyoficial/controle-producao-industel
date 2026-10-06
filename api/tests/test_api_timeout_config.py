from __future__ import annotations

from api.tests.conftest import API_TEST_TIMEOUT_SECONDS


def test_api_tests_use_the_longer_timeout(request):
    marker = request.node.get_closest_marker("timeout")
    assert marker is not None
    assert marker.args == (API_TEST_TIMEOUT_SECONDS,)
