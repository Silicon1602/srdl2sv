import argparse
import os
import time
import logging
from itertools import chain

logging_map = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "NONE": logging.NOTSET
}

class CliArguments():

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description="SystemRDL 2 SystemVerilog compiler")

        self.parser.add_argument(
            "-b",
            "--bus",
            choices=['amba3ahblite'],
            default='amba3ahblite',
            help="Set the bus protocol that shall be used by software to ',\
                  communicate with the registers. (default: %(default)s)")

        self.parser.add_argument(
            "-o",
            "--out_dir",
            type=str,
            default="./srdl2sv_out",
            help="Define output directory to dump files.\
                  If directory is non-existent, it will be created.\
                  (default: %(default)s)")

        self.parser.add_argument(
            "-d",
            "--search_paths",
            type=str,
            nargs="+",
            help="Point to one (or more) directories that will\
                  be searched for RDL files.")

        self.parser.add_argument(
            "-r",
            "--recursive_search",
            action="store_true",
            help="If set, the dependency directories will be\
                  searched recursively.")

        self.parser.add_argument(
            "-e",
            "--disable_enums",
            action="store_true",
            help="Disable enumeration generation. This will prevent the\
                  compiler from generating packages and it will prevent\
                  it from using enums in the port list.")

        self.parser.add_argument(
            "--stream_log_level",
            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'NONE'],
            default='WARNING',
            help="Set verbosity level of output to shell. When set to 'NONE',\
                  nothing will be printed to the shell. (default: %(default)s)")

        self.parser.add_argument(
            "--file_log_level",
            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'NONE'],
            default='INFO',
            help="Set verbosity level of output to log-file. When set to 'NONE',\
                  nothing will be printed to the shell. (default: %(default)s)")

        self.parser.add_argument(
            "--real_tabs",
            action="store_true",
            help="Use tabs, rather than spaces, for tabs")

        self.parser.add_argument(
            "--tab_width",
            type=int,
            default=4,
            help="Define how many tabs or spaces will be contained\
                  in one level of indentation. (default: %(default)s)")


        self.parser.add_argument(
            "IN_RDL",
            type=str,
            nargs="+",
            help="Location of RDL file(s) with root addrmap.")

    def get_config(self) -> dict():
        args = self.parser.parse_args()

        # Create dictionary to save config in
        config = dict()
        config['list_args'] = list()

        # Save input file and output directory to dump everything in
        config['input_file'] = args.IN_RDL
        config['output_dir'] = args.out_dir
        config['list_args'].append('Ouput Directory  : {}'.format(config['output_dir']))

        # Create output directory
        try:
            os.makedirs(config['output_dir'])
        except FileExistsError:
            pass

        # Map logging level string to integers
        config['stream_log_level'] = logging_map[args.stream_log_level]
        config['file_log_level'] = logging_map[args.file_log_level]
        config['list_args'].append('Stream Log Level : {}'.format(args.stream_log_level))
        config['list_args'].append('File Log Level   : {}'.format(args.file_log_level))

        # Determine paths to be passed to systemrdl-compiler to search
        # for include files.
        if args.recursive_search:
            config['search_paths'] = [x[0] for y in args.search_paths for x in os.walk(y)]
        else:
            config['search_paths'] = args.search_paths

        if not config['search_paths']:
            config['search_paths'] = []

        # Save timestamp, so that it can be used across the compiler
        config['ts'] = time.localtime()

        # Determine name of file to hold logs
        ts = time.strftime('%Y%m%d_%H%M%S', config['ts'])
        config['file_log_location'] = "/".join([config['output_dir'], "srdl2sv_{}.log".format(ts)])

        # Tab style
        config['real_tabs'] = args.real_tabs
        config['tab_width'] = args.tab_width

        config['list_args'].append('Use Real Tabs    : {}'.format(config['real_tabs']))
        config['list_args'].append('Tab Width        : {}'.format(config['tab_width']))

        # Set enums
        config['enums'] = not args.disable_enums
        config['list_args'].append('Enums Enabled    : {}'.format(config['enums']))

        # Set bus
        config['bus'] = args.bus
        config['list_args'].append('Register Bus Type: {}'.format(config['bus']))

        if args.bus == 'amba3ahblite':
            config['addrwidth'] = 32

        # Set version
        config['version'] = '0.01'

        return config
