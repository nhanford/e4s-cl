import os
import shlex
import json
from e4s_cl import tests
from e4s_cl.cf.libraries import host_libraries
from e4s_cl.cf.storage.levels import PROFILE_STORAGE
from e4s_cl.cli.commands.launch import COMMAND
from e4s_cl.cli.cli_view import CreateCommand
from e4s_cl.model.profile import Profile


class LaunchTest(tests.TestCase):
    def setUp(self):
       self.resetStorage()

       if data := os.getenv('__E4S_CL_TEST_PROFILE', {}):
           CreateCommand(Profile, __name__)._create_record(PROFILE_STORAGE, json.loads(data))

    def tearDown(self):
       self.resetStorage()

    @tests.skipIf(not os.getenv('__E4S_CL_TEST_LAUNCHER'), "No environment information")
    def test_launch(self):
        self.assertCommandReturnValue(0, COMMAND, shlex.split(os.getenv('__E4S_CL_TEST_LAUNCHER')) + [os.getenv('__E4S_CL_TEST_BINARY')])