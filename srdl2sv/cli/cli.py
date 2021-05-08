import argparse
import os
from itertools import chain

class CliArguments():
    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description="SystemRDL 2 SystemVerilog compiler")

        self.parser.add_argument(
            "-v",
            "--verbosity",
            action="count",
            help="Increase output verbosity.")

        self.parser.add_argument(
            "-q",
            "--quiet",
            action="store_true")

        self.parser.add_argument(
            "-o",
            "--out_dir",
            type=str,
            help="Define output directory to dump files.\
                  If directory is non-existent, it will be created.")

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
                  searched recursively.");

        self.parser.add_argument(
            "IN_RDL",
            type=str,
            nargs="+",
            help="Location of RDL file(s) with root addrmap.")

    def get_config(self) -> dict():
        args = self.parser.parse_args()

        config = dict()

        config['input_file'] = args.IN_RDL
        config['verbosity'] = args.verbosity
        config['quiet'] = args.quiet

        if args.recursive_search:
            config['search_paths'] = [x[0] for y in args.search_paths for x in os.walk(y)]
        else:
            config['search_paths'] = args.search_paths

        return config
