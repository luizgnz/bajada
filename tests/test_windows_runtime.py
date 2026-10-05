from types import SimpleNamespace
from windows_runtime import detach_console


def test_detached_gui_has_valid_streams_for_shutdown():
    streams = SimpleNamespace()
    kernel = SimpleNamespace(FreeConsole=lambda: True)
    assert detach_console(kernel, streams)
    try:
        streams.stdout.write('diagnostic output')
        streams.stderr.write('diagnostic error')
        streams.stdout.flush()
        streams.stderr.flush()
        assert streams.stdin.read() == ''
        assert streams.stdout is streams.__stdout__
        assert streams.stderr is streams.__stderr__
        assert streams.stdin is streams.__stdin__
    finally:
        streams.stdout.close()
        streams.stderr.close()
        streams.stdin.close()


def test_no_console_leaves_existing_streams_unchanged():
    original = object()
    streams = SimpleNamespace(stdout=original)
    assert not detach_console(SimpleNamespace(FreeConsole=lambda: False), streams)
    assert streams.stdout is original
