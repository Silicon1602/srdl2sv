#!/usr/bin/env python3

# Standard modules
import sys
import time

# Imported modules
from systemrdl import RDLCompiler, RDLCompileError

# Local modules
from components.addrmap import AddrMap
from cli.cli import CliArguments
from log.log import create_logger

if __name__ == "__main__":
    # Take start timestamp
    start = time.time()

    # Construct command line arguments
    cli_arguments = CliArguments()
    config = cli_arguments.get_config()

    # Compile and elaborate files provided from the command line
    rdlc = RDLCompiler()

    try:
        for input_file in config['input_file']:
            rdlc.compile_file(
                input_file, incl_search_paths=config['search_paths'])

        root = rdlc.elaborate()
    except RDLCompileError:
        sys.exit(1)

    addrmap = AddrMap(rdlc, root.top)

    logger = create_logger(
        __name__,
        stream_log_level=config['stream_log_level'],
        file_log_level=config['file_log_level'],
        file_name=config['file_log_location'])
    logger.info("Elapsed time: %f seconds", time.time() - start)
