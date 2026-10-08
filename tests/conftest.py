"""Shared fixtures for the Home Assistant harness tests."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.synergy_csv.const import CONF_METER_NAME, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(recorder_mock: object, enable_custom_integrations: None) -> None:
    """Let the harness find custom_components/ in this repo.

    ``recorder_mock`` is listed first: the recorder must be set up before ``hass``
    (which ``enable_custom_integrations`` pulls in), and the integration depends on it.
    """


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="Home", data={CONF_METER_NAME: "Home"}, unique_id="home"
    )


@pytest.fixture
def fake_upload() -> Callable[[bytes | str], contextlib.AbstractContextManager[None]]:
    """Make ``process_uploaded_file`` hand the flow a file with the given content."""

    @contextlib.contextmanager
    def _patch(content: bytes | str, tmp_dir: Path | None = None) -> Iterator[None]:
        import tempfile

        raw = content.encode() if isinstance(content, str) else content
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upload.csv"
            path.write_bytes(raw)

            @contextlib.contextmanager
            def _process(hass: object, file_id: str) -> Iterator[Path]:
                yield path

            with patch("custom_components.synergy_csv.config_flow.process_uploaded_file", _process):
                yield

    return _patch


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()
