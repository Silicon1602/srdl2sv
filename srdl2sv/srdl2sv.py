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
        stdout_log_level=config['stdout_log_level'],
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
        logger.fatal("Could not find '%s'", input_file)
        sys.exit(1)

    addrmaps = AddrMap(root.top, config)

    # Determine address width
    if config['addrwidth_bus_spec']:
        logger.info("Set address width to '%i', according to '%s' specification",
                     config['addrwidth'], config['bus'])
    else:
        logger.info("Set address width to '%i'", config['addrwidth'])

    # Save RTL to file
    for addrmap in addrmaps.get_addrmaps():
        out_addrmap_file = f"{config['output_dir']}/{addrmap.name}.sv"

        with open(out_addrmap_file, 'w', encoding='UTF-8') as file:
            print(
                addrmap.get_rtl(
                    tab_width=config['tab_width'],
                    real_tabs=config['real_tabs']
                ),
                file=file
            )

            logger.info("Succesfully created '%s'", out_addrmap_file)

        # Start grabbing packages. This returns a dictionary for the main addrmap
        # and all it's child regfiles/addrmaps
        for key, value in addrmap.get_package_rtl(
            tab_width=config['tab_width'],
            real_tabs=config['real_tabs']
        ).items():
            if value:
                with open(f"{config['output_dir']}/{key}_pkg.sv", 'w', encoding="UTF-8") as file:
                    print(value, file=file)

    # Copy over generic srdl2sv_interface_pkg
    widget_if_rtl = pkg_resources.read_text(widgets, "srdl2sv_widget_if.sv")

    out_if_file = f"{config['output_dir']}/srdl2sv_widget_if.sv"

    with open(out_if_file, 'w', encoding="UTF-8") as file:
        print(widget_if_rtl, file=file)

    logger.info("Copied 'srdl2sv_widget_if.sv'")

    # Copy over widget RTL from widget directory
    try:
        widget_rtl = pkg_resources.read_text(widgets, f"srdl2sv_{config['bus']}.sv")

        out_widget_file = f"{config['output_dir']}/srdl2sv_{config['bus']}.sv"

        with open(out_widget_file, 'w', encoding="UTF-8") as file:
            print(widget_rtl, file=file)

        logger.info("Selected, implemented, and copied '%s' widget", config['bus'])
    except FileNotFoundError:
        # Bus might not have a corresponding SV file
        logger.info("Did not find a seperate SystemVerilog file for '%s' widget", config['bus'])


    # Print elapsed time
    logger.info("Elapsed time: %f seconds", time.time() - start)

if __name__ == "__main__":
    main()
