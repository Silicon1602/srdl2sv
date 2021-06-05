#!/usr/bin/env python3

# Standard modules
import sys
import time
import os
import importlib.resources as pkg_resources

# Imported modules
from systemrdl import RDLCompiler, RDLCompileError

# Local modules
from components.addrmap import AddrMap
from cli.cli import CliArguments
from log.log import create_logger
from components import widgets

if __name__ == "__main__":
    # Take start timestamp
    start = time.time()

    # Construct command line arguments
    cli_arguments = CliArguments()
    config = cli_arguments.get_config()

    # Create logger
    logger = create_logger(
        __name__,
        stream_log_level=config['stream_log_level'],
        file_log_level=config['file_log_level'],
        file_name=config['file_log_location'])

    # Compile and elaborate files provided from the command line
    rdlc = RDLCompiler()

    try:
        for input_file in config['input_file']:
            rdlc.compile_file(
                input_file, incl_search_paths=config['search_paths'])

        root = rdlc.elaborate()
    except RDLCompileError:
        sys.exit(1)

    addrmap = AddrMap(root.top, config)

    # Create output directory
    try:
        os.makedirs(config['output_dir'])
        logger.info('Succesfully created directory "{}"'.format(
            config['output_dir']))
    except FileExistsError:
        logger.info('Directory "{}" does already exist'.format(
            config['output_dir']))

    # Save RTL to file
    # Start out with addrmap
    out_addrmap_file = "{}/{}.sv".format(config['output_dir'], addrmap.name)

    with open(out_addrmap_file, 'w') as file:
        file.write(
            addrmap.get_rtl(
                tab_width=config['tab_width'],
                real_tabs=config['real_tabs']
            )
        )

        logger.info('Succesfully created "{}"'.format(out_addrmap_file))

    # Start grabbing packages. This returns a dictionary for the main addrmap
    # and all it's child regfiles/addrmaps
    for key, value in addrmap.get_package_rtl(
        tab_width=config['tab_width'],
        real_tabs=config['real_tabs']
    ).items():
        with open('{}/{}_pkg.sv'.format(config['output_dir'], key), 'w') as file:
            file.write(value)

    # Copy over widget RTL from widget directory
    widget_rtl = pkg_resources.read_text(widgets, '{}.sv'.format(config['bus']))

    out_widget_file = "{}/{}.sv".format(config['output_dir'], config['bus'])

    with open(out_widget_file, 'w') as file:
        file.write(widget_rtl)

    logger.info("Elapsed time: %f seconds", time.time() - start)
