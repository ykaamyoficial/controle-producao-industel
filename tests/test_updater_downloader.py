from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.downloader import DownloadError, TransientDownloadError, download_package


class _FakeStreamingResponse:
    def __init__(self, *, status_code: int, body: bytes, headers: dict | None = None):
        self.status_code = status_code
        self._body = body
        self._headers = headers or {}

    def header(self, name: str):
        return self._headers.get(name)

    def iter_bytes(self, chunk_size: int):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]


class _FakeCtx:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, exc_type, exc, tb):
        return False


def _opener_returning(response: _FakeStreamingResponse):
    return lambda url: _FakeCtx(response)


def _opener_raising(exc: Exception):
    class _Ctx:
        def __enter__(self_inner):
            raise exc

        def __exit__(self_inner, *a):
            return False

    return lambda url: _Ctx()


def _opener_sequence(items):
    iterator = iter(items)

    def _open(url):
        item = next(iterator)
        if isinstance(item, Exception):
            class _Ctx:
                def __enter__(self_inner):
                    raise item

                def __exit__(self_inner, *a):
                    return False
            return _Ctx()
        return _FakeCtx(item)

    return _open


class LocalSourceDownloadTests(unittest.TestCase):
    def test_copies_local_file_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "pkg.zip"
            source.write_bytes(b"payload-bytes")
            dest_dir = tmp / "dest"
            result = download_package(str(source), dest_dir)
            self.assertEqual(result.read_bytes(), b"payload-bytes")
            self.assertFalse((dest_dir / "pkg.zip.part").exists())

    def test_missing_local_source_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadError):
                download_package(str(Path(tmp) / "does-not-exist.zip"), Path(tmp) / "dest")

    def test_local_source_size_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "pkg.zip"
            source.write_bytes(b"12345")
            with self.assertRaises(DownloadError):
                download_package(str(source), tmp / "dest", expected_size=999)


class HttpSourceDownloadTests(unittest.TestCase):
    def test_successful_http_download_leaves_no_part_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            response = _FakeStreamingResponse(status_code=200, body=b"X" * 1000, headers={"content-length": "1000"})
            result = download_package(
                "http://example.invalid/pkg.bin", dest_dir, expected_size=1000,
                stream_opener=_opener_returning(response),
            )
            self.assertEqual(result.stat().st_size, 1000)
            self.assertFalse((dest_dir / "pkg.bin.part").exists())

    def test_server_error_is_transient_and_retried_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            failing = _FakeStreamingResponse(status_code=503, body=b"")
            succeeding = _FakeStreamingResponse(status_code=200, body=b"OK-DATA")
            result = download_package(
                "http://example.invalid/pkg.bin", dest_dir, max_retries=2, retry_backoff_seconds=0.01,
                stream_opener=_opener_sequence([failing, succeeding]),
            )
            self.assertEqual(result.read_bytes(), b"OK-DATA")

    def test_client_error_is_permanent_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            response = _FakeStreamingResponse(status_code=404, body=b"")
            with self.assertRaises(DownloadError):
                download_package("http://example.invalid/pkg.bin", dest_dir, stream_opener=_opener_returning(response))

    def test_network_exception_is_transient_and_exhausts_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            opener = _opener_sequence([TimeoutError("slow"), TimeoutError("slow"), TimeoutError("slow")])
            with self.assertRaises(TransientDownloadError):
                download_package("http://example.invalid/pkg.bin", dest_dir, max_retries=2, retry_backoff_seconds=0.01, stream_opener=opener)

    def test_interrupted_download_leaves_no_part_or_final_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            opener = _opener_sequence([ConnectionResetError("reset")])
            with self.assertRaises(TransientDownloadError):
                download_package("http://example.invalid/pkg.bin", dest_dir, max_retries=0, stream_opener=opener)
            self.assertFalse((dest_dir / "pkg.bin.part").exists())
            self.assertFalse((dest_dir / "pkg.bin").exists())

    def test_size_exceeding_expected_is_rejected_mid_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp)
            response = _FakeStreamingResponse(status_code=200, body=b"X" * 2000)
            with self.assertRaises(DownloadError):
                download_package("http://example.invalid/pkg.bin", dest_dir, expected_size=1000, stream_opener=_opener_returning(response))
            self.assertFalse((dest_dir / "pkg.bin.part").exists())


if __name__ == "__main__":
    unittest.main()
