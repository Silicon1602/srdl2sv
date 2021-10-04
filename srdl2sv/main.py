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
    except FileNotFoundError:
        logger.fatal("Could not find '{}'".format(input_file))
        sys.exit(1)

    addrmap = AddrMap(root.top, config)

    # Save RTL to file
    # Start out with addrmap
    out_addrmap_file = "{}/{}.sv".format(config['output_dir'], addrmap.name)

    with open(out_addrmap_file, 'w') as file:
        print(
            addrmap.get_rtl(
                tab_width=config['tab_width'],
                real_tabs=config['real_tabs']
            ),
            file=file
        )

        logger.info('Succesfully created "{}"'.format(out_addrmap_file))

    # Start grabbing packages. This returns a dictionary for the main addrmap
    # and all it's child regfiles/addrmaps
    for key, value in addrmap.get_package_rtl(
        tab_width=config['tab_width'],
        real_tabs=config['real_tabs']
    ).items():
        if value:
            with open('{}/{}_pkg.sv'.format(config['output_dir'], key), 'w') as file:
                print(value, file=file)

    # Copy over widget RTL from widget directory
    widget_rtl = pkg_resources.read_text(widgets, 'srdl2sv_{}.sv'.format(config['bus']))

    out_widget_file = "{}/srdl2sv_{}.sv".format(config['output_dir'], config['bus'])

    with open(out_widget_file, 'w') as file:
        print(widget_rtl, file=file)

    logger.info("Selected, implemented, and copied '{}' widget".format(config['bus']))

    # Copy over generic srdl2sv_interface_pkg
    widget_if_rtl = pkg_resources.read_text(widgets, 'srdl2sv_if_pkg.sv')

    out_if_file = "{}/srdl2sv_if_pkg.sv".format(config['output_dir'])

    with open(out_if_file, 'w') as file:
        widget_if_rtl_parsed = widget_if_rtl.format(
            regwidth_bit = addrmap.get_regwidth() - 1,
            regwidth_byte = int(addrmap.get_regwidth() / 8) - 1,
            addrwidth = config['addrwidth'] - 1)

        print(widget_if_rtl_parsed,file=file)

    logger.info("Copied 'srdl2sv_if_pkg.sv")

    # Print elapsed time
    logger.info("Elapsed time: %f seconds", time.time() - start)
