![srdl2sv logo](images/srdl2sv_logo.gif)
# Table of Contents
1. [Introduction](#introduction)
    1. [Non-production ready](#non-production-ready)
2. [Getting started](#getting-started)
    1. [Installation](#installation)
    2. [Compiling your first RDL](#compiling-your-first-rdl)
    3. [Using the generated RTL](#using-the-generated-rtl)
3. [Supported bus protocols](#supported-bus-protocols)
4. [Help function](#help-functions)
5. [Contributing](#contributing)
6. [License](#license)
7. [Limitations](#limitations)

# Introduction 
srdl2sv is a [SystemRDL 2.0](https://www.accellera.org/images/downloads/standards/systemrdl/SystemRDL_2.0_Jan2018.pdf) to (synthesizable) [SystemVerilog](https://ieeexplore.ieee.org/document/8299595/versions) compiler. The tool is based on based on [SystemRDL/systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler). 
## Non-production ready
Warning: This software is still under development and not yet ready for use in production. 
# Getting started
## Installation
A `setup.py` file is provided to install srdl2sv and all dependencies. At the time of writing this, the software was only tested on Linux but there should not be anything that prevents it from running on MacOS, Windows, or any other OS with Python >= 3.8.

To install srdl2sv globally on your Linux machine, first clone the repository:

```
git clone dennispotter.eu:Dennis/srdl2sv.git
```
enter the local repository repository
```
cd srdl2sv
```
and run
```
sudo python3 setup.py install
```

## Compiling your first RDL
The argument that is required to get started is the location of the SystemRDL file that contains the root address map. The compiler will generate a seperate SystemVerilog module for each address map it encounters in the code. Thus, if address maps are instantiated within other address maps, these will be packed into a seperate module.

To compile a file called `example_addrmap.rdl`, simply run:
```
srdl2sv example_addrmap.rdl
```
By default, the compiler will create a directory called `srdl2sv_out` and dump `example_addrmap.sv` with the actual RTL and a log file that contains `INFO`-level logging into this directory. To change the logging level, use `--file_log_level` like shown below:

```
srdl2sv example_addrmap.rdl
    --stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
```
Similarly, to change the default log level of the output to the shell, which is `WARNING`, use `--stream_log_level` like shown below:
```
srdl2sv example_addrmap.rdl
    --stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
    --file_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
```
If the RDL file includes other RDL files, the directories that contain these files must be passed to the compiler as follows:

```
srdl2sv example_addrmap.rdl
    --search_paths SEARCH_PATHS [SEARCH_PATHS ...]
```
By default, the compiler will generate SystemVerilog enumerations if SystemRDL enums are used. These enums are dumped in a seperate package to be included outside of the register module. To turn off this feature, use the flag `--disable_enums`:
```
srdl2sv example_addrmap.rdl
    --disable_enums
```
By default, the registers in the RTL are byte-addressable. If this is not required it is recommened to turn off byte-addressing by using the flag `--no_byte_enable` to achieve more efficient results in synthesis:
```
srdl2sv example_addrmap.rdl
    --no_byte_enable
```
## Using the generated RTL

# Supported bus protocols
The following bus protocols are supported:
- AMBA 3 AHB-Lite Protocol (default)

The following bus protocols are planned at this point:
- AMBA 3 APB Protocol

# Help function
A comprehensive help function of the tool can be invoked by running `srdl2sv --help`.
```
usage: main.py [-h] [-b {amba3ahblite}] [-c DESCRIPTIONS]
               [-d SEARCH_PATHS [SEARCH_PATHS ...]] [-e]
               [--file_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}]
               [--stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}]
               [--no_byte_enable] [-o OUT_DIR] [-r] [--real_tabs]
               [--tab_width TAB_WIDTH]
               IN_RDL [IN_RDL ...]

SystemRDL 2 SystemVerilog compiler

positional arguments:
  IN_RDL                Location of RDL file(s) with root addrmap.

optional arguments:
  -h, --help            show this help message and exit
  -b {amba3ahblite}, --bus {amba3ahblite}
                        Set the bus protocol that shall be used by software to
                        ', communicate with the registers. (default:
                        amba3ahblite)
  -c DESCRIPTIONS, --descriptions DESCRIPTIONS
                        Include descriptions of addrmaps (+16), regfiles (+8),
                        memories (+4) registers (+2), and fields (+1) in RTL.
                        This is a bitfield.
  -d SEARCH_PATHS [SEARCH_PATHS ...], --search_paths SEARCH_PATHS [SEARCH_PATHS ...]
                        Point to one (or more) directories that will be
                        searched for RDL files.
  -e, --disable_enums   Disable enumeration generation. This will prevent the
                        compiler from generating packages and it will prevent
                        it from using enums in the port list.
  --file_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to log-file. When set to
                        'NONE', nothing will be printed to the shell.
                        (default: INFO)
  --stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to shell. When set to
                        'NONE', nothing will be printed to the shell.
                        (default: WARNING)
  --no_byte_enable      If this flag gets set, byte-enables get disabled. At
                        that point, it is only possible to address whole
                        registers, not single bytes within these registers
                        anymore.
  -o OUT_DIR, --out_dir OUT_DIR
                        Define output directory to dump files. If directory is
                        non-existent, it will be created. (default:
                        ./srdl2sv_out)
  -r, --recursive_search
                        If set, the dependency directories will be searched
                        recursively.
  --real_tabs           Use tabs, rather than spaces, for tabs
  --tab_width TAB_WIDTH
                        Define how many tabs or spaces will be contained in
                        one level of indentation. (default: 4)
```
# Contributing
# License
The source code of srdl2sv (i.e., the actual RTL generator) is licensed under the [GPLv3](LICENSE). All templates in [srdlsv/components/templates](srdlsv/components/templates) and [srdlsv/components/widgets](srdlsv/components/widgets) are licensed under the [MIT](LICENSE.MIT) license. Therefore, all RTL that is generated by srdl2sv is also licensed under the MIT license.

# Limitations
- [Any limitations to the systemrdl-compiler](https://systemrdl-compiler.readthedocs.io/en/latest/known_issues.html) also apply to the SystemRDL2SystemVerilog compiler.
- Depth of a hierarchy is limited to 26 levels. 
