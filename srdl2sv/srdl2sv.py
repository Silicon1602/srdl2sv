#!/usr/bin/env python3

# Standard modules
import sys
import time
import importlib.resources as pkg_resources

# Imported modules
from systemrdl import RDLCompiler, RDLCompileError

# Local modules
from srdl2sv.components.addrmap import AddrMap
from srdl2sv.components import widgets
from srdl2sv.cli.cli import CliArguments
from srdl2sv.log.log import create_logger

def main():
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
        logger.fatal(f"Could not find '{input_file}'")
        sys.exit(1)

    addrmap = AddrMap(root.top, config)

    # Save RTL to file
    # Start out with addrmap
    out_addrmap_file = f"{config['output_dir']}/{addrmap.name}.sv"

    with open(out_addrmap_file, 'w', encoding='UTF-8') as file:
        print(
            addrmap.get_rtl(
                tab_width=config['tab_width'],
                real_tabs=config['real_tabs']
            ),
            file=file
        )

        logger.info(f"Succesfully created '{out_addrmap_file}'")

    # Start grabbing packages. This returns a dictionary for the main addrmap
    # and all it's child regfiles/addrmaps
    for key, value in addrmap.get_package_rtl(
        tab_width=config['tab_width'],
        real_tabs=config['real_tabs']
    ).items():
        if value:
            with open(f"{config['output_dir']}/{key}_pkg.sv", 'w', encoding="UTF-8") as file:
                print(value, file=file)

    # Copy over widget RTL from widget directory
    widget_rtl = pkg_resources.read_text(widgets, f"srdl2sv_{config['bus']}.sv")

    out_widget_file = f"{config['output_dir']}/srdl2sv_{config['bus']}.sv"

    with open(out_widget_file, 'w', encoding="UTF-8") as file:
        print(widget_rtl, file=file)

    logger.info(f"Selected, implemented, and copied '{config['bus']}' widget")

    # Copy over generic srdl2sv_interface_pkg
    widget_if_rtl = pkg_resources.read_text(widgets, 'srdl2sv_if_pkg.sv')

    out_if_file = f"{config['output_dir']}/srdl2sv_if_pkg.sv"

    with open(out_if_file, 'w', encoding="UTF-8") as file:
        widget_if_rtl_parsed = widget_if_rtl.format(
            regwidth_bit = addrmap.get_regwidth() - 1,
            regwidth_byte = int(addrmap.get_regwidth() / 8) - 1,
            addrwidth = config['addrwidth'] - 1)

        print(widget_if_rtl_parsed,file=file)

    logger.info("Copied 'srdl2sv_if_pkg.sv")

    # Print elapsed time
    logger.info("Elapsed time: %f seconds", time.time() - start)

if __name__ == "__main__":
    main()
