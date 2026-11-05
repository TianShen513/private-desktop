"""Bounded subprocess output: desktop content never spills to temporary files."""

from __future__ import annotations

import subprocess
import threading
import os

MAX_OUTPUT = 2 * 1024 * 1024


class ProcessError(Exception):
    """A subprocess failed without exposing its output in an exception."""


def cancel_reader(reader: threading.Thread) -> None:
    """Cancel a Windows synchronous pipe read without closing it on this thread."""
    if os.name != "nt" or not reader.is_alive() or reader.native_id is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.CancelSynchronousIo.argtypes = [wintypes.HANDLE]
    kernel.CancelSynchronousIo.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenThread(0x0001, False, reader.native_id)  # THREAD_TERMINATE access
    if handle:
        try:
            kernel.CancelSynchronousIo(handle)
        finally:
            kernel.CloseHandle(handle)


def capture(argv: list[str], *, timeout: float = 20, limit: int = MAX_OUTPUT) -> bytes:
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False, bufsize=0,
        )
    except (OSError, ValueError):
        raise ProcessError("process_unavailable") from None
    output: list[bytes] = []

    def read() -> None:
        try:
            assert process.stdout is not None
            chunks = []
            size = 0
            while size <= limit:
                chunk = process.stdout.read(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            data = b"".join(chunks)
            output.append(data)
            if len(data) > limit:
                process.kill()
        except (OSError, ValueError):
            output.append(b"")
        finally:
            # The reading thread owns the handle. Closing it elsewhere can wait
            # for an inherited pipe to reach EOF on Windows, defeating timeouts.
            if process.stdout is not None:
                process.stdout.close()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            reader.join(timeout=2)
            raise ProcessError("process_timeout") from None
        reader.join(timeout=2)
        if reader.is_alive() or not output or len(output[0]) > limit:
            raise ProcessError("output_limit")
        if process.returncode:
            raise ProcessError("process_failed")
        return output[0]
    finally:
        if reader.is_alive():
            cancel_reader(reader)
            reader.join(timeout=0.2)
