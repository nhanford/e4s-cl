"""Launch command

Definition of arguments and hooks related to the launch command,
launcher detection, profile loading, and subprocess creation.
"""

import os
from pathlib import Path
from argparse import ArgumentTypeError, Namespace
from e4s_cl import EXIT_SUCCESS, E4S_CL_SCRIPT
from e4s_cl import logger, util
from e4s_cl.variables import is_debug
from e4s_cl.cli import arguments
from e4s_cl.cli.command import AbstractCommand
from e4s_cl.model.profile import Profile

LOGGER = logger.get_logger(__name__)
_SCRIPT_CMD = os.path.basename(E4S_CL_SCRIPT)


def _argument_profile(string):
    """Argument type callback.
    Asserts the entered string matches a defined profile."""
    profile = Profile.controller().one({'name': string})

    if not profile:
        raise ArgumentTypeError("Profile {} does not exist".format(string))
    return profile


def _argument_path(string):
    """Argument type callback.
    Asserts that the string corresponds to an existing path."""
    return Path(string.strip()).as_posix()


def _argument_path_comma_list(string):
    """Argument type callback.
    Asserts that the string corresponds to a list of existing paths."""
    return [_argument_path(data) for data in string.split(',')]


def _parameters(args):
    """Generate compound parameters by merging profile and cli arguments
    The profile's parameters have less priority than the ones specified on
    the command line.
    If no profile is given, try to load the selected one."""
    if isinstance(args, Namespace):
        args = vars(args)

    parameters = dict(args.get('profile', Profile.selected()))

    for attr in ['image', 'backend', 'libraries', 'files']:
        if args.get(attr, None):
            parameters.update({attr: args[attr]})

    return parameters


def _format_execute(parameters):
    from e4s_cl.cli.commands.execute import COMMAND as execute_cmd
    execute_command = str(execute_cmd).split()

    # Insert a top-level e4s option between the script name and the subcommand
    execute_command = [E4S_CL_SCRIPT, '--slave'] + execute_command[1:]

    if is_debug():
        execute_command = [execute_command[0]] + ['--debug'
                                                  ] + execute_command[1:]

    for attr in ['image', 'backend']:
        if parameters.get(attr, None):
            execute_command += ["--{}".format(attr), parameters[attr]]

    for attr in ['libraries', 'files']:
        if parameters.get(attr, None):
            execute_command += [
                "--{}".format(attr), ",".join(parameters[attr])
            ]

    return execute_command


class LaunchCommand(AbstractCommand):
    """``launch`` subcommand."""
    def _construct_parser(self):
        usage = "%s [arguments] [launcher] [launcher_arguments] [--] <command> [command_arguments]" % self.command
        parser = arguments.get_parser(prog=self.command,
                                      usage=usage,
                                      description=self.summary)
        parser.add_argument('--profile',
                            type=_argument_profile,
                            help="Name of the profile to use",
                            default=arguments.SUPPRESS,
                            metavar='profile')
        parser.add_argument('--image',
                            type=_argument_path,
                            help="Container image to use",
                            metavar='image')
        parser.add_argument('--files',
                            type=_argument_path_comma_list,
                            help="Files to bind, comma-separated",
                            metavar='files')
        parser.add_argument('--libraries',
                            type=_argument_path_comma_list,
                            help="Libraries to bind, comma-separated",
                            metavar='libraries')
        parser.add_argument('--backend',
                            help="Container backend to use",
                            metavar='solution')
        parser.add_argument('cmd',
                            help="Executable command, e.g. './a.out'",
                            metavar='command',
                            nargs=arguments.REMAINDER)
        return parser

    def main(self, argv):
        args = self._parse_args(argv)

        if not args.cmd:
            self.parser.error("No command given")

        launcher, program = util.interpret_launcher(args.cmd)
        execute_command = _format_execute(_parameters(args))

        LOGGER.debug(" ".join(launcher + execute_command + program))
        util.create_subprocess_exp(launcher + execute_command + program)

        return EXIT_SUCCESS


COMMAND = LaunchCommand(__name__, summary_fmt="Launch a process")
