"""
Module introducing shifter support
"""

import os
import subprocess
import tempfile
from pathlib import Path
from e4s_cl import logger, CONTAINER_DIR
from e4s_cl.util import which, run_subprocess
from e4s_cl.cf.containers import Container, FileOptions, BackendNotAvailableError

LOGGER = logger.get_logger(__name__)

NAME = 'shifter'
MIMES = []

OPTION_STRINGS = {FileOptions.READ_ONLY: 'ro', FileOptions.READ_WRITE: 'rw'}

_DEFAULT_CONFIG_PATH = Path('/etc/shifter/udiRoot.conf')


def _deprettify(lines):
    """
    Reconstruct full directives out of directives separated by backslashes
    over multiple lines
    """
    buffer, full_lines = '', []

    for line in lines:
        buffer = buffer + line

        if buffer.endswith('\\'):
            buffer = buffer.rstrip('\\')
            continue

        full_lines.append(buffer)
        buffer = ''

    return full_lines


def _directives_to_dict(directives):
    """
    Transform a list of strings of shape 'KEY=value[=foo]' into a dict
    """
    entries = []

    # Split all the directives at the first '='
    for directive in directives:
        parts = directive.split('=', 1)

        if len(parts) != 2:
            LOGGER.warning("Unrecognized directive: '%s'", directive)
            continue

        entries.append(tuple(map(lambda x: x.strip(), parts)))

    return dict(entries)


def _parse_config(config_file: Path):
    """
    Parse a file at a given path and return a dict with its defined variables
    """
    # Read the given file
    try:
        with open(config_file, 'r', encoding='utf-8') as config:
            config_directives = _deprettify(
                [l.strip() for l in config.readlines()])
    except IOError as err:
        LOGGER.warning("Error opening configuration file: %s", str(err))
        return {}

    # Remove all comments
    config_directives = set(
        filter(lambda x: not x.startswith('#'), config_directives))

    # Organize the results in a dict
    return _directives_to_dict(config_directives)


class ShifterContainer(Container):
    """
    Class to use for a shifter execution
    """

    executable_name = 'shifter'

    @classmethod
    @property
    def linker_path(cls):
        config = _parse_config(_DEFAULT_CONFIG_PATH)

        path = []

        for module in config.get('defaultModules', '').split(','):
            prepend = config.get(f"module_{module}_siteEnvPrepend")
            if prepend:
                for var in prepend.split():
                    if var.startswith('LD_LIBRARY_PATH'):
                        path.append(var.split('=')[1])

        return os.pathsep.join(path).split(os.pathsep)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executable = which(self.__class__.executable_name)

    def _setup_import(self, where: Path) -> str:
        """
        Create a temporary directory to bind /.e4s-cl files in
        """
        volumes = [(where.as_posix(), CONTAINER_DIR)]

        for source, destination, _ in self.bound:
            if destination.as_posix().startswith(CONTAINER_DIR):
                rebased = destination.as_posix()[len(CONTAINER_DIR) + 1:]
                temporary = Path(where, rebased)

                LOGGER.debug("Shifter: Creating %s for %s in %s",
                             temporary.as_posix(), source.as_posix(),
                             destination.as_posix())
                os.makedirs(temporary.parent, exist_ok=True)
                with subprocess.Popen(
                    ['cp', '-r',
                     source.as_posix(),
                     temporary.as_posix()]) as proc:
                    proc.wait()

            elif source.is_dir():
                if destination.as_posix().startswith('/etc'):
                    LOGGER.error(
                        "Shifter: Backend does not support binding to '/etc'")
                    continue

                volumes.append((source.as_posix(), destination.as_posix()))

            else:
                LOGGER.warning(
                    "Shifter: Failed to bind '%s': Backend does not support file"
                    "binding. Performance may be impacted.", source)

        return [f"--volume={source}:{dest}" for (source, dest) in volumes]

    def _prepare(self, command):
        env_list = []
        if self.ld_preload:
            env_list.append(f'--env=LD_PRELOAD={":".join(self.ld_preload)}')
        if self.ld_lib_path:
            env_list.append(
                f'--env=LD_LIBRARY_PATH={":".join(self.ld_lib_path)}')

        for env_var in self.env.items():
            env_list.append(f'--env={env_var}={env_var}')

        self.temp_dir = tempfile.TemporaryDirectory()
        volumes = self._setup_import(Path(self.temp_dir.name))
        return [
            self.executable, f"--image={self.image}", *env_list, *volumes,
            *command
        ]

    def run(self, command):

        if not which(self.executable):
            raise BackendNotAvailableError(self.executable)

        container_cmd = self._prepare(command)
        LOGGER.debug(container_cmd)
        return run_subprocess(container_cmd, env=self.env)


CLASS = ShifterContainer