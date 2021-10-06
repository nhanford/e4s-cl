"""
Module introducing shifter support
"""

import os
from pathlib import Path
from e4s_cl import logger
from e4s_cl.util import create_subprocess_exp
from e4s_cl.cf.libraries import host_libraries
from e4s_cl.cf.containers import Container, FileOptions

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

    def run(self, command, redirect_stdout=False):
        env_list=[]
        env_list.append('--env=LD_PRELOAD=%s' % ":".join(self.ld_preload))
        env_list.append('--env=LD_LIBRARY_PATH=%s' % ":".join(self.ld_lib_path))

        for env_var in self.env.items():
            env_list.append('--env=%s=%s' % env_var)

        container_cmd = [self.executable, "--image=%s" % self.image, *env_list, *command]
        return create_subprocess_exp(container_cmd,
                                     env=self.env,
                                     redirect_stdout=redirect_stdout)


CLASS = ShifterContainer
