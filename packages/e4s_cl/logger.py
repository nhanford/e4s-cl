"""E4S Container Launcher logging.

E4S CL has two channels for communicating with the user:
    1) sys.stdout via :any:`print`.
       Use this for messages the user has requested, e.g. a project listing.
    2) sys.stdout and sys.stderr via :any:`e4s_cl.logger`.
       Use this for status messages generated by E4S CL.

E4S CL also logs all status messages at the highest reporting level to
a rotating debug file in the user's E4S CL directory, typically "~/.local/e4s_cl".
"""

import os
import re
import sys
import time
import textwrap
import socket
import platform
import string
import logging
import json
from pathlib import Path
from logging import handlers, FileHandler
from datetime import datetime
from e4s_cl import USER_PREFIX, E4S_CL_VERSION
from e4s_cl.variables import is_master
from e4s_cl.cf.json_handler import JSONHandler
from e4s_cl.cf.relay_logger import RelayLogger
import termcolor

# Use isatty to check if the stream supports color
STDOUT_COLOR = os.isatty(sys.stdout.fileno())
STDERR_COLOR = os.isatty(sys.stderr.fileno())

# This is used all over the project, so name translation here
get_logger = logging.getLogger

WARNING = logging.WARNING
ERROR = logging.ERROR


def handle_error(line: str, default_level: int = WARNING) -> bool:
    """
    From a line of error stream, check if it has been generated from a
    JSONHandler

    line: string to parse
    default_level: level to log with in case the line is not a record

    Returns False in case the line is not a JSONrecord
    """
    logging_data = JSONHandler.validate(line)

    if not logging_data:
        # Its does not come from a child e4s-cl process
        # Log it with the requested level
        _CHILD_LOGGER.log(default_level, line)
        return

    extra = {
        'name': logging_data.get('name'),
        'created': logging_data.get('created'),
        'process': logging_data.get('process'),
        'host': logging_data.get('host'),
    }

    process_logger = _CHILD_LOGGER.getChild(
        "%s.%d" % (logging_data.get('host'), logging_data.get('process')))

    # If the logger was created for the first time at the above step,
    # Set it to output to a dedicated file
    if FILE_LOGGING and not process_logger.handlers:
        logname = "%s/%s.%s.log" % (_LOG_FILE_PREFIX, logging_data.get('host'),
                                    logging_data.get('process'))
        process_logger.addHandler(FileHandler(logname, delay=True))

    process_logger.log(logging_data.get('levelno', logging.NOTSET),
                       logging_data.get('msg'),
                       extra=extra)

    return True


def _prune_ansi(line: str) -> str:
    """
    Remove ANSI color codes from a string
    """
    return re.sub(re.compile('\x1b[^m]+m'), '', line)


def get_terminal_size():
    """Discover the size of the user's terminal.
    
    Several methods are attempted depending on the user's OS.
    If no method succeeds then default to (80, 25).
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters.
    """
    default_width = 80
    default_height = 25
    dims = _get_term_size_env()

    if not dims:
        dims = _get_term_size_posix()

        if not dims:
            dims = default_width, default_height

    try:
        dims = list(map(int, dims))
    except ValueError:
        dims = default_width, default_height

    width = dims[0] if dims[0] >= 10 else default_width
    height = dims[1] if dims[1] >= 1 else default_height

    return width, height


def _get_term_size_tput():
    """Discover the size of the user's terminal via `tput`_.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
               
    .. _tput: http://stackoverflow.com/questions/263890/how-do-i-find-the-width-height-of-a-terminal-window
    """
    try:
        import subprocess
        proc = subprocess.Popen(["tput", "cols"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
        output = proc.communicate(input=None)
        cols = int(output[0])
        proc = subprocess.Popen(["tput", "lines"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
        output = proc.communicate(input=None)
        rows = int(output[0])
        return (cols, rows)
    except:  # pylint: disable=bare-except
        return None


def _get_term_size_posix():
    """Discover the size of the user's terminal on a POSIX operating system (e.g. Linux).
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
    """

    # This function follows a POSIX naming scheme, not Python's.
    # pylint: disable=invalid-name
    # Sometimes Pylint thinks termios doesn't exist or doesn't have certain members even when it does.
    # pylint: disable=no-member
    def ioctl_GWINSZ(fd):
        try:
            import fcntl
            import termios
            import struct
            dims = struct.unpack('hh',
                                 fcntl.ioctl(fd, termios.TIOCGWINSZ, '1234'))
        except:  # pylint: disable=bare-except
            return None
        return dims

    dims = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not dims:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            dims = ioctl_GWINSZ(fd)
            os.close(fd)
        except:  # pylint: disable=bare-except
            pass
    if not dims:
        return None
    return int(dims[1]), int(dims[0])


def _get_term_size_env():
    """Discover the size of the user's terminal via environment variables.
    
    The user may set the LINES and COLUMNS environment variables to control E4S CL's
    console dimension calculations.
    
    Returns:
        tuple: (width, height) tuple giving the dimensions of the user's terminal window in characters,
               or None if the size could not be determined.
    """
    try:
        return (int(os.environ['COLUMNS']), int(os.environ['LINES']))
    except (KeyError, ValueError):
        return None


def on_stdout(function):

    def wrapper(obj, record):
        text = function(obj, record)
        if STDOUT_COLOR:
            return text
        return _prune_ansi(text)

    return wrapper


def on_stderr(function):

    def wrapper(obj, record):
        text = function(obj, record)
        if STDERR_COLOR:
            return text
        return _prune_ansi(text)

    return wrapper


class LogFormatter(logging.Formatter):
    """Custom log message formatter.
    
    Controls message formatting for all levels.
    
    Args:
        line_width (int): Maximum length of a message line before line is wrapped.
        printable_only (bool): If True, never send unprintable characters to :any:`sys.stdout`.
    """
    # Allow invalid function names to define member functions named after logging levels.
    # pylint: disable=invalid-name

    _printable_chars = set(string.printable)

    def __init__(self, line_width, printable_only=False, allow_colors=True):
        super().__init__()
        self.printable_only = printable_only
        self.allow_colors = allow_colors
        self.line_width = line_width
        self._text_wrapper = textwrap.TextWrapper(width=self.line_width,
                                                  break_long_words=False,
                                                  break_on_hyphens=False,
                                                  drop_whitespace=False)

    @on_stderr
    def CRITICAL(self, record):
        return self._colored(self._format_message(record), 'red', None,
                             ['bold'])

    @on_stderr
    def ERROR(self, record):
        return self._colored(self._format_message(record), 'red', None,
                             ['bold'])

    @on_stderr
    def WARNING(self, record):
        return self._colored(self._format_message(record), 'yellow', None,
                             ['bold'])

    @on_stdout
    def INFO(self, record):
        return self._format_message(record)

    @on_stderr
    def DEBUG(self, record):
        message = record.getMessage()
        if self.printable_only and (not set(message).issubset(
                self._printable_chars)):
            message = "<<UNPRINTABLE>>"

        if __debug__:
            marker = self._colored(
                "[%s %s:%s]" %
                (record.levelname.title(), record.name, record.lineno),
                'yellow')
        else:
            marker = self._colored(
                "[%s %s:%d]" %
                (record.levelname.title(), getattr(
                    record, 'host', 'localhost'), record.process), 'cyan',
                None, ['bold'])

        return '%s %s' % (marker, message)

    def format(self, record):
        """Formats a log record.
        
        Args:
            record (LogRecord): LogRecord instance to format.
        
        Returns:
            str: The formatted record message.
            
        Raises:
            RuntimeError: No format specified for a the record's logging level.
        """
        try:
            return getattr(self, record.levelname)(record)
        except AttributeError:
            raise RuntimeError('Unknown record level (name: %s)' %
                               record.levelname)

    def _colored(self, text, *color_args):
        """Insert ANSII color formatting via `termcolor`_.
        
        Text colors:
            * grey
            * red
            * green
            * yellow
            * blue
            * magenta
            * cyan
            * white
        
        Text highlights:
            * on_grey
            * on_red
            * on_green
            * on_yellow
            * on_blue
            * on_magenta
            * on_cyan
            * on_white

        Attributes:
            * bold
            * dark
            * underline
            * blink
            * reverse
            * concealed
        
        .. _termcolor: http://pypi.python.org/pypi/termcolor
        """
        if self.allow_colors and color_args:
            return termcolor.colored(text, *color_args)
        return text

    def _format_message(self, record, header=''):
        # Length of the header, pruned from invisible escape characters
        header_length = len(_prune_ansi(header))

        output = []
        text = record.getMessage().split("\n")

        # Strip empty lines at the end only
        while len(text) > 1 and not text[-1]:
            text.pop()

        for line in text:
            output += textwrap.wrap(line,
                                    width=(self.line_width - header_length))
            if not line:
                output += ['']

        return textwrap.indent("\n".join(output), header, lambda line: True)


def set_log_level(level):
    """Sets :any:`LOG_LEVEL`, the output level for stdout logging objects.
    
    Changes to LOG_LEVEL may affect software package verbosity. 
    
    Args:
        level (str): A string identifying the logging level, e.g. "INFO".
    """
    # Use of global statement is justified in this case.
    # pylint: disable=global-statement
    global LOG_LEVEL
    LOG_LEVEL = level.upper()
    _STDERR_HANDLER.setLevel(LOG_LEVEL)


def debug_mode():
    return LOG_LEVEL == 'DEBUG'


LOG_LEVEL = 'INFO'
"""str: The global logging level for stdout loggers and software packages.

Don't change directly. May be changed via :any:`set_log_level`.  
"""

LOG_FILE = Path(USER_PREFIX, 'debug_log')
"""str: Absolute path to a log file to receive all debugging output."""

TERM_SIZE = get_terminal_size()
"""tuple: (width, height) tuple of detected terminal dimensions in characters."""

LINE_WIDTH = TERM_SIZE[0]
"""Width of a line on the terminal.

Uses system specific methods to determine console line width.  If the line
width cannot be determined, the default is 80.
"""

_ROOT_LOGGER = logging.getLogger()
if not _ROOT_LOGGER.handlers:
    _ROOT_LOGGER.setLevel(logging.DEBUG)
    _LOG_FILE_PREFIX = LOG_FILE.parent

    # Use a different handler depending on the type of execution
    if is_master():
        # If top-level, output to stderr
        _STDERR_HANDLER = logging.StreamHandler(sys.stderr)
        _STDERR_HANDLER.setFormatter(
            LogFormatter(line_width=LINE_WIDTH, printable_only=False))
        _STDERR_HANDLER.setLevel(LOG_LEVEL)

    else:
        # If post-launcher, use JSON records on stderr
        _STDERR_HANDLER = JSONHandler(sys.stderr)

    _ROOT_LOGGER.addHandler(_STDERR_HANDLER)

    # Setup the file logging
    FILE_LOGGING = True

    try:
        # Ensure the log file directory is accessible
        Path.mkdir(_LOG_FILE_PREFIX, exist_ok=True)

        handle = open(LOG_FILE, 'w')
        handle.close()
    except OSError as exc:
        _ROOT_LOGGER.debug("Failed to open file logger: %s", exc.strerror)
        FILE_LOGGING = False

    if FILE_LOGGING:
        _FILE_HANDLER = handlers.TimedRotatingFileHandler(LOG_FILE,
                                                          when='D',
                                                          interval=1,
                                                          backupCount=3)
        _FILE_HANDLER.setFormatter(
            LogFormatter(line_width=120, allow_colors=False))
        _FILE_HANDLER.setLevel(logging.DEBUG)
        _ROOT_LOGGER.addHandler(_FILE_HANDLER)

    if is_master():
        # pylint: disable=logging-not-lazy
        _ROOT_LOGGER.debug(
            ("\n%(bar)s\n"
             "E4S CONTAINER LAUNCHER LOGGING INITIALIZED\n"
             "\n"
             "Timestamp         : %(timestamp)s\n"
             "Hostname          : %(hostname)s\n"
             "Platform          : %(platform)s\n"
             "Version           : %(version)s\n"
             "Python Version    : %(pyversion)s\n"
             "Working Directory : %(cwd)s\n"
             "Terminal Size     : %(termsize)s\n"
             "Frozen            : %(frozen)s\n"
             "%(bar)s\n") % {
                 'bar': '#' * LINE_WIDTH,
                 'timestamp': str(datetime.now()),
                 'hostname': socket.gethostname(),
                 'platform': platform.platform(),
                 'version': E4S_CL_VERSION,
                 'pyversion': platform.python_version(),
                 'cwd': os.getcwd(),
                 'termsize': 'x'.join([str(_) for _ in TERM_SIZE]),
                 'frozen': getattr(sys, 'frozen', False)
             })

if is_master():
    # Separate logger managing output from child processes
    _CHILD_LOGGER = logging.getLogger("processes")
    _CHILD_LOGGER.addHandler(_STDERR_HANDLER)

    # Records passed to this tree of loggers will be written to specific files,
    # no need to pass them along to the root logger and make a copy in the log file
    _CHILD_LOGGER.propagate = False
else:
    _CHILD_LOGGER = logging.getLogger()

# Ensure a custom, more permissive class is used when asking for a new logger
_CHILD_LOGGER.manager.setLoggerClass(RelayLogger)
