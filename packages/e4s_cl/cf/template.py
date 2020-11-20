import os, stat
import tempfile
from e4s_cl import logger

LOGGER = logger.get_logger(__name__)

TEMPLATE = """#!/bin/bash -i
# The shell need to be interactive for spack commands
# see https://github.com/spack/spack/issues/11098

%s

# Affirm the urgency of using the host libraries, as spack may override
# this variable
export LD_LIBRARY_PATH=%s:$LD_LIBRARY_PATH

%s
"""


def setUp(command, libdir, setup=None):
    if setup:
        setup_line = "source %s" % setup
    else:
        setup_line = ''

    if isinstance(command, list):
        command = " ".join(command)

    script = tempfile.NamedTemporaryFile('w', delete=False)
    script.write(TEMPLATE % (setup_line, libdir, command))
    script.close()

    os.chmod(script.name, 0o755)

    LOGGER.debug("Running templated script:\n" + TEMPLATE, setup_line, libdir,
                 command)

    return script.name


def tearDown(file_name):
    if os.path.exists(file_name):
        os.unlink(file_name)