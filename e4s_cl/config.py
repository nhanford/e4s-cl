import yaml
from os.path import expanduser, exists

confxGlobal = {'container directory': 'CONTAINER_DIR', 'launcher options': 'LAUNCHER_OPTIONS', 'container options': 'CONTAINER_OPTIONS'}

user_home = expanduser('~')
default_config_path = user_home + "/.config/e4s-cl.yaml"
alternate_config_path = "/etc/e4s-cl/e4s-cl.yaml"
configuration_file = ""

class Configuration:
    updated_globals = dict()

    def __init__(self, confFile):
        with open(confFile) as f:
            self.data = yaml.safe_load(f)
        for key in self.data.keys():
            global_key = confxGlobal[key]
            self.updated_globals.update({confxGlobal[key]: self.data[key]})

if exists(default_config_path):
    configuration_file = default_config_path 
elif exists(alternate_config_path):
    configuration_file = alternate_config_path 
            
CONFIGURATION_VALUES = None

if CONFIGURATION_VALUES is None and configuration_file:
    CONFIGURATION_VALUES = Configuration(configuration_file).updated_globals


def configuration_options(option, VALUES=CONFIGURATION_VALUES):
    if VALUES:
        if VALUES.get(option):
            return VALUES.get(option).split()
    return []
