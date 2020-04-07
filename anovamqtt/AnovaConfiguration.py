from configparser import ConfigParser

class AnovaConfiguration(ConfigParser):
    def __init__(self):
        self.home_dir = "."
        self.config_dir= "{}/config".format(self.home_dir)
        self.config_file = "{}/AnovaMQTT.cfg".format(self.config_dir)
        super().__init__()
        config_handle = open(self.config_file)
        self.readfp(config_handle)
        config_handle.close()
        self.add_defaults()

    def add_defaults(self):
        if (not self.has_section('main')):
            self.add_section('main')
        if (not self.has_option('main', 'log_file')):
            self.set('main', 'log_file', 'anovamqtt.log')
        if (not self.has_option('main', 'log_level')):
            self.set('main', 'log_level', 'INFO')
