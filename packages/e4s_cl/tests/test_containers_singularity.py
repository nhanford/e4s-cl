from os import getenv, getcwd
from unittest import skipIf
from pathlib import Path
from e4s_cl import tests
from e4s_cl.util import which
from e4s_cl.cf.containers import Container, BackendUnsupported, FileOptions


class ContainerTestSingularity(tests.TestCase):
    def singularity_check():
        return (not which('singularity') and (not Path('singularity').exists()))


    def test_create(self):
        container = Container(executable='singularity', image='test')
        self.assertFalse(type(container) == Container)
        self.assertTrue(isinstance(container, Container))

    @skipIf(singularity_check(), "Singularity absent from system")
    def test_run_backend(self):
        container = Container(executable='singularity')
        command = ['']
        container_cmd, env = container.run(command,redirect_stdout=False)
        self.assertIn('singularity',' '.join(map(str,container_cmd)))
    
    def test_run_image(self):
        container = Container(executable='singularity', image='imagenametest')
        command = ['']
        container_cmd, env = container.run(command,redirect_stdout=False, test_run=True)
        self.assertIn('imagenametest',' '.join(map(str,container_cmd)))
    
    def test_run_pwd(self):
        container = Container(executable='singularity')
        command = ['']
        container_cmd, env = container.run(command,redirect_stdout=False, test_run=True)
        pwd = getcwd()
        self.assertIn(pwd,' '.join(map(str,container_cmd)))

    def test_run_mpirun(self):
        container = Container(executable='singularity', image='dummyimagename')
        command = ['mpirun -n 2 ls']
        container_cmd, env = container.run(command,redirect_stdout=False, test_run=True)
        self.assertIn(command[0],' '.join(map(str,container_cmd)))

    def test_bind_file(self):
        container = Container(executable='singularity')

        target = Path('/tmp')
        dest = Path('/tmp')
        option = FileOptions.READ_WRITE

        container.bind_file(target)
        self.assertIn((target, target, FileOptions.READ_ONLY),
                      list(container.bound))

        container.bind_file(target, dest=dest)
        self.assertIn((target, dest, FileOptions.READ_ONLY),
                      list(container.bound))

        container.bind_file(target, dest=dest, option=option)
        self.assertIn((target, dest, FileOptions.READ_WRITE),
                      list(container.bound))

    def test_bind_relative(self):
        container = Container(executable='singularity')

        target = Path('/tmp/../proc/meminfo')

        ref = Path('/tmp')
        file = Path('/proc/meminfo')
        home = Path.home()
        
        container.bind_file(target)
        files = set(map(lambda x: x[0], container.bound))

        self.assertSetEqual({ref, file, home}, files)