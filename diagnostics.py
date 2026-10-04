"""Local error reports and recovery for Python callbacks; no network telemetry."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import sys
from core import state_directory

_fault_stream = None


def install_diagnostics(window=None, directory=None):
    global _fault_stream
    logger = logging.getLogger('bajada')
    if not logger.handlers:
        try:
            directory = directory or state_directory()
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / 'errors.log', maxBytes=1_000_000,
                                          backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(handler)
            logger.setLevel(logging.ERROR)
            logger.propagate = False
            fault_path = directory / 'crash.log'
            if fault_path.exists() and fault_path.stat().st_size > 1_000_000:
                fault_path.replace(directory / 'crash-previous.log')
            _fault_stream = fault_path.open('a', encoding='utf-8')
            faulthandler.enable(file=_fault_stream, all_threads=True)
        except OSError:
            logger.addHandler(logging.NullHandler())

    def report_error(error_type, error, traceback):
        logger.error('Unhandled callback error', exc_info=(error_type, error, traceback))
        if window is not None:
            try:
                window.handle_unexpected_error()
            except Exception:
                logger.exception('Could not recover the interface')
        else:
            sys.__excepthook__(error_type, error, traceback)

    sys.excepthook = report_error
