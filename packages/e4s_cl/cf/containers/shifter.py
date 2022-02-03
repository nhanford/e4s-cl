"""
Module introducing shifter support
"""

import os
import subprocess
import tempfile
from pathlib import Path
from e4s_cl import logger, CONTAINER_DIR
from e4s_cl.cf.containers import Container, FileOptions, BackendNotAvailableError

LOGGER = logger.get_logger(__name__)

NAME = 'shifter'
EXECUTABLES = ['shifter']
MIMES = []

OPTION_STRINGS = {FileOptions.READ_ONLY: 'ro', FileOptions.READ_WRITE: 'rw'}


class ShifterContainer(Container):
    """
    Class to use for a shifter execution
    """

    def __setup__(self):
        pass

    def __setup_import(self) -> str:
        """
        Create a temporary directory to bind /.e4s-cl files in
        """

        # The following directory will hold the files bound to the container
        # The file is deleted once the object is deleted
        self.__shifter_e4s_dir = tempfile.TemporaryDirectory()
        LOGGER.debug("Generating import template in '%s'",
                     self.__shifter_e4s_dir.name)

        volumes = [(self.__shifter_e4s_dir.name, CONTAINER_DIR)]

        for source, destination, _ in self.bound:
            if destination.as_posix().startswith(CONTAINER_DIR):
                rebased = destination.as_posix()[len(CONTAINER_DIR) + 1:]
                temporary = Path(self.__shifter_e4s_dir.name, rebased)

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
                    "Shifter: Backend does not support file binding. Performance may be impacted."
                )

        return [f"--volume={source}:{dest}" for (source, dest) in volumes]

    def run(self, command, redirect_stdout=False, test_run=False):

        if not test_run and (not self.executable or
                             (not Path(self.executable).exists())):
            raise BackendNotAvailableError(self.executable)

        env_list = []
        if self.ld_preload:
            env_list.append(f'--env=LD_PRELOAD={":".join(self.ld_preload)}')
        if self.ld_lib_path:
            env_list.append(
                f'--env=LD_LIBRARY_PATH={":".join(self.ld_lib_path)}')

        for env_var in self.env.items():
            env_list.append(f'--env={env_var}={env_var}')

        volumes = self.__setup_import()

        container_cmd = [
            self.executable, f"--image={self.image}", *env_list, *volumes,
            *command
        ]
        return (container_cmd, self.env)


CLASS = ShifterContainer
