"""Detach the GUI console while keeping Python streams valid through shutdown."""
import os
import sys


def detach_console(kernel32=None, streams=None):
    if kernel32 is None:
        import ctypes
        kernel32 = ctypes.windll.kernel32
    if not kernel32.FreeConsole():
        return False
    streams = sys if streams is None else streams
    # FreeConsole invalidates console handles. Retaining those streams can make
    # writes/flushes fail, including Python's final flush (exit code 120).
    streams.stderr = streams.__stderr__ = open(os.devnull, 'w', encoding='utf-8')
    streams.stdout = streams.__stdout__ = open(os.devnull, 'w', encoding='utf-8')
    streams.stdin = streams.__stdin__ = open(os.devnull, 'r', encoding='utf-8')
    return True
