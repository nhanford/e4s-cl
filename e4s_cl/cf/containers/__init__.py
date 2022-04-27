"""
Defines an abstract class to simplify the use of container technology.
Creating an instance of ``Container`` will return a specific class to
the required backend.

To implement support for a new container backend, create a submodule
that posesses the following attributes:
    - NAME: The name identifying the backend
    - EXECUTABLES: List of executables the backend uses; if not accessible on the
        PATH, the backend will be disabled
    - MIMES: if the backend uses files, extensions used to guess the backend from
        an image
    - CLASS: the class to use. The class' `run` method will be used when launching
        the container: refer to its docstring for details
"""

import os
import re
import sys
import json
from importlib import import_module
from tempfile import TemporaryFile
from pathlib import Path
from typing import Union
from e4s_cl import (EXIT_FAILURE, E4S_CL_HOME, CONTAINER_DIR,
                    CONTAINER_LIBRARY_DIR, CONTAINER_SCRIPT, E4S_CL_SCRIPT,
                    logger)
from e4s_cl.variables import ParentStatus
from e4s_cl.util import walk_packages, which, json_loads, run_e4scl_subprocess
from e4s_cl.cf.version import Version
from e4s_cl.cf.libraries import LibrarySet
from e4s_cl.error import ConfigurationError

LOGGER = logger.get_logger(__name__)

# List of available modules, accessible by their "executable" or cli tool names
BACKENDS = {}

# List of available, non-debug backends, for help and completion
EXPOSED_BACKENDS = []

# Used to identify backends by the image's suffix
# list of tuples containing (suffix, backend_name)
MIMES = []


# pylint: disable=too-few-public-methods
class FileOptions:
    """
    Abstraction of bound files options
    """
    READ_ONLY = 0
    READ_WRITE = 1


class BackendError(ConfigurationError):
    """Error raised when the requested container tech is not available"""

    def __init__(self, backend_name):
        self.offending = backend_name
        self._message = f"An error has been encountered setting up the container technology backend {backend_name}."
        super().__init__(self._message)

    def handle(self, etype, value, tb):
        LOGGER.critical(self._message)
        return EXIT_FAILURE


class BackendNotAvailableError(BackendError):
    """Error raised when the requested backend is not found on the system"""

    def __init__(self, backend_name):
        super().__init__(backend_name)
        self._message = f"Backend {self.offending} not found. Is the module loaded ?"


class BackendUnsupported(BackendError):
    """Error raised when the requested backend is not supported"""

    def __init__(self, backend_name):
        super().__init__(backend_name)
        pretty = 's are' if len(EXPOSED_BACKENDS) > 1 else ' is'
        self._message = f"""Backend {self.offending} not supported at this time.
The available backend{pretty}: {", ".join(EXPOSED_BACKENDS)}.
Please create a GitHub issue if support is required."""


class AnalysisError(ConfigurationError):
    """Generic error for container analysis failure"""

    def __init__(self, returncode):
        self.code = returncode
        super().__init__(f"Container analysis failed ! ({self.code})")

    def handle(self, etype, value, tb):
        LOGGER.critical("Container analysis failed ! (%d)", self.code)
        return EXIT_FAILURE


def dump(func):
    """
    If verbose, output a description of the container about to be run before
    launching it.

    This needs to be a decorator as it is wraps the run() method implemented
    in every backend module.
    """

    def wrapper(*args, **kwargs):
        self = func.__self__

        LOGGER.debug(str(self))

        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


class Container:
    """
    Abstract class that auto-completes depending on the container tech
    """

    # pylint: disable=too-few-public-methods
    class BoundFile:
        """
        Element of the bound file dictionnary
        """

        def __init__(self, path: Path, option: int = FileOptions.READ_ONLY):
            self.path = Path(path)
            self.option = option

    # pylint: disable=unused-argument
    def __new__(cls, image=None, name=None):
        """
        Object level creation hijacking: depending on the executable
        argument, the appropriate subclass will be returned.
        """
        module_name = BACKENDS.get(name)
        if module_name:
            module = sys.modules.get(module_name)
        else:
            raise BackendUnsupported(name)

        driver = object.__new__(module.CLASS)

        # If in debugging mode, print out the config before running
        if logger.debug_mode():
            driver.run = dump(driver.run)
        driver.__str__ = dump(driver.__str__)

        return driver

    def __init__(self, image=None, name=None):
        """
        Common class init: this code is run in the actual sub-classes
        """

        # Container image identifier
        self.image = image

        # User-set parameters
        # Files to bind: dict(guest_path -> (host_path, options))
        # dict[Path, Container._bound_file]
        self.__bound_files = {}
        self.env = {}  # Environment
        self.ld_preload = []  # Files to put in LD_PRELOAD
        self.ld_lib_path = []  # Directories to put in LD_LIBRARY_PATH

        self.libc_v = Version('0.0.0')
        self.libraries = LibrarySet()

        if hasattr(self, '__setup__'):
            self.__setup__()

    @property
    def script(self):
        return Path(CONTAINER_SCRIPT)

    @property
    def import_dir(self):
        return Path(CONTAINER_DIR)

    @property
    def import_library_dir(self):
        return Path(CONTAINER_LIBRARY_DIR)

    def get_data(self):
        """
        Run the e4s-cl analyze command in the container to analyze the
        environment inside of it. The results will be used to tailor the
        library import to ensure compatibility of the shared objects.

        The entrypoint passed as an argument may contain external parameters
        (The source script being one of them)

        A library set with data about libraries listed in library_set will
        be returned
        """
        outstream = sys.stdout

        with TemporaryFile() as buffer:
            sys.stdout = buffer

            code = self.run(['ldd', '--version'])

            if code:
                raise AnalysisError(code)

            sys.stdout.seek(0, 0)
            out = sys.stdout.read().decode()
            LOGGER.debug("Output of ldd --version: %s", out)
            self.libc_v = Version(out)

        sys.stdout = outstream

        return set()

    def bind_file(self,
                  path: Union[Path, str],
                  dest=None,
                  option=FileOptions.READ_ONLY) -> None:
        """
        If there is no destination, handle files with relative paths.
        For instance on summit, some files are required as
        /jsm_pmix/container/../lib/../bin/file
        Although only /jsm_pmix/bin/file is required, not
        having jsm_pmix/container && lib makes it error out
        unrelative returns a list of all the paths required for such a file
        """
        if not path:
            return

        def _unrelative(string):
            """
            Returns a list of all the directories referenced by a relative path
            """

            def _contains(path1, path2):
                """
                Returns true if path2 is in the tree of which path1 is the root
                pathlib's < operator compares alphabetically, so here we are
                """
                index = len(path1.parts)
                return path1.parts[:index] == path2.parts[:index]

            path = Path(string)
            visited = {path, path.resolve()}
            deps = set()

            for i, part in enumerate(path.parts):
                if part == '..':
                    visited.add(Path(*path.parts[:i]).resolve())

            for element in visited:
                contained = False
                for path in visited:
                    if path != element and _contains(path, element):
                        contained = True

                if not contained:
                    deps.add(element)

            return [p.as_posix() for p in deps]

        if not dest:
            for _path in _unrelative(path):
                self.__bound_files.update(
                    {Path(_path): Container.BoundFile(_path, option)})
        else:
            self.__bound_files.update(
                {Path(dest): Container.BoundFile(path, option)})

    @property
    def bound(self):
        for path, data in self._Container__bound_files.items():
            if data.path.exists():
                yield data.path, path, data.option
            else:
                LOGGER.warning(
                    "Attempting to bind non-existing file: %(source)s to %(dest)s",
                    {
                        'source': data.path,
                        'dest': path
                    })

    def bind_env_var(self, key, value):
        self.env.update({key: value})

    def add_ld_preload(self, path):
        if path not in self.ld_preload:
            self.ld_preload.append(path)

    def add_ld_library_path(self, path):
        if path not in self.ld_lib_path:
            self.ld_lib_path.append(path)

    def run(self, command):
        """
        run a command in a container.

        command         list[str]   the command line to execute

        This method must be implemented in the container module.
        It should take into account the parameters set in the object:
        - The bound files in self.bound;
        - The environment variables self.env;
        - The LD_PRELOAD self.ld_preload;
        - The LD_LIBRARY_PATH self.ld_lib_path
        and set them to be available in the created container.
        """
        raise NotImplementedError(
            f"`run` method not implemented for container module {self.__class__.__name__}"
        )

    def __str__(self):
        out = []
        out.append(f"{self.__class__.__name__} object:")
        if self.image:
            out.append(f"- image: {self.image}")
        bound_files = "\n".join(
            [f"\t{v[0]} -> {v[1]} ({v[2]})" for v in self.bound])
        out.append(f"- bound:\n{bound_files}")
        if self.env:
            out.append(f"- env: { json.dumps(self.env, indent=2)}")
        if self.ld_preload:
            out.append(
                f"- LD_PRELOAD: {json.dumps(self.ld_preload, indent=2)}")
        if self.ld_lib_path:
            out.append(
                f"- LD_LIBRARY_PATH: {json.dumps(self.ld_lib_path, indent=2)}")
        return '\n'.join(out)


def guess_backend(path):
    suffix = Path(path).suffix

    matches = list(filter(lambda x: x[0] == suffix, MIMES))

    # If we cannot associate a unique backend to a MIME
    if len(matches) != 1:
        return None

    return matches[0][1]


def assert_module(_module) -> bool:
    """
    Assert a module defining a container class is properly structured
    """
    required = ['NAME', 'CLASS']

    for attribute in required:
        if not hasattr(_module, attribute):
            LOGGER.warning(
                "Container module '%s' is missing a required attribute: %s; skipping ...",
                _module.__name__, required)
            return False

    if getattr(_module, 'CLASS') and not getattr(_module.CLASS, 'run'):
        LOGGER.warning(
            "Container module '%s' has an incomplete module class; skipping ..."
        )

    return True


for _, _module_name, _ in walk_packages(__path__, prefix=__name__ + "."):
    import_module(_module_name)
    _module = sys.modules[_module_name]

    if not assert_module(_module):
        continue

    BACKENDS.update({
        _module.NAME: _module_name,
    })

    if not getattr(_module, 'DEBUG_BACKEND', False):
        EXPOSED_BACKENDS.append(_module.NAME)

    for mimetype in getattr(_module, 'MIMES', []):
        MIMES.append((mimetype, _module.NAME))