![srdl2sv logo](images/srdl2sv_logo.gif)
# Table of Contents
1. [Introduction](#introduction)
    1. [Not production ready](#non-production-ready)
2. [Getting started](#getting-started)
    1. [Installation](#installation)
    2. [Quick start into RDL compilation](#quick-start-into-rdl-compilation)
    3. [Using the generated RTL](#using-the-generated-rtl)
3. [Supported bus protocols](#supported-bus-protocols)
4. [Help function](#help-functions)
5. [Contributing](#contributing)
6. [License](#license)
7. [Limitations](#limitations)

# Introduction 
srdl2sv is a [SystemRDL 2.0](https://www.accellera.org/images/downloads/standards/systemrdl/SystemRDL_2.0_Jan2018.pdf) to (synthesizable) [SystemVerilog](https://ieeexplore.ieee.org/document/8299595/versions) compiler. The tool is based on based on [SystemRDL/systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler). 
## Not production ready
Warning: This software is still under development and not yet ready for use in production. Many SystemRDL features are implemented but srdl2sv is still under active development and almost all tests are yet to be written.
# Getting started
## Installation
A `setup.py` file is provided to install srdl2sv and all dependencies. At the time of writing this, the software has only been tested on Linux but there should not be anything that prevents it from running on MacOS, Windows, or any other OS with Python >= 3.8.

To install srdl2sv globally on your Linux machine, first clone the repository:

```
git clone https://github.com/Silicon1602/srdl2sv
```
enter the local repository repository
```
cd srdl2sv
```
and run
```
sudo python3 setup.py install
```

## Quick start into RDL compilation
The argument that is required to get started is the location of the SystemRDL file that contains the root address map. The compiler will generate a seperate SystemVerilog module for each address map it encounters in the code. Thus, if address maps are instantiated within other address maps, these will be packed into a seperate module.

To compile a file called `example_addrmap.rdl`, simply run:
```
srdl2sv example_addrmap.rdl
```
By default, the compiler will create a directory called `srdl2sv_out` and dump `example_addrmap.sv` with the actual RTL. By default, the program wil not dump any logging into this directory. To change the logging level, use `--file_log_level` like shown below:

```
srdl2sv example_addrmap.rdl
    --stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
```
Similarly, to change the default log level of the output to the shell, which is `INFO`, use `--stream_log_level` like shown below:
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
For the generated RTL to work, all files in `srdl2sv_out` (or in a custom directory, if specified with `-o` must be passed on to the respective EDA tool for proper functioning. For a better understanding of the files that get generated, a short summary below.

A run with only 1 `addrmap`, without any enumerations, and with `--bus simple` will generate 2 files:
```
srdl2sv_out/
├─ <addrmap_name>.sv
├─ srdl2sv_widget_if.sv
```
The former file is the actual SystemVerilog module that contains all register logic. The latter contains a SystemVerilog `interface` that is internally being used to enable communication with the registers. It is worth noting that the `interface` is **not** brought up to the module's interface but is flattened out for compatibility reasons.

If one decides to al create a bus protocol (see [Supported bus protocols](#supported-bus-protocols)), an additional file will be created that contains a SHIM between the protocol and the internal bus logic.
```
srdl2sv_out/
├─ <addrmap_name>.sv
├─ srdl2sv_widget_if.sv
├─ srdl2sv_<protocol_name>.sv
```
If an `addrmap` calls other `addrmaps`, each will get it's own SystemVerilog module. For example, if `<addrmap_name>` from the previous example would instantiate `<addrmap1_name>` and `<addrmap2_name>`, the following files would be generated:
```
srdl2sv_out/
├─ <addrmap_name>.sv
├─ <addrmap1_name>.sv
├─ <addrmap2_name>.sv
├─ srdl2sv_widget_if.sv
```
In case we only 1 `addrmap` is compiled, that address map contains enumerations, and `--disable_enums` is *not* set, a seperate package will be generated that defines those enums. These enumerations are used in the module's I/O interface but can also be easily used outside of the `<addrmap_name>.sv`. That way, the code outside of the register block becomes more readable and a user gets all benefits of SystemVerilog's strong type checking. 
```
srdl2sv_out/
├─ <addrmap_name>.sv
├─ srdl2sv_widget_if.sv
├─ <addrmap_name>_pkg.sv
```
If the address map from the aforementioned example contains `regfiles`, these will open a seperate scope to prevent naming collisions. For example's sake, let's assume it instantiates the `regfiles` `<regfile_1>` and `<regfile_2>`. In that case, the following files would be dumped:
```
srdl2sv_out/
├─ <addrmap_name>.sv
├─ srdl2sv_widget_if.sv
├─ <addrmap_name>_pkg.sv
├─ <addrmap_name>__<regfile_1>_pkg.sv
├─ <addrmap_name>__<regfile_2>_pkg.sv
```
# Supported bus protocols
The following standardized bus protocols are supported:
- None
- AMBA 3 AHB-Lite Protocol **(default)**

The following bus protocols are planned at this point:
- AMBA 3 APB Protocol

# Help function
A comprehensive help function of the tool can be invoked by running `srdl2sv --help`.
```
usage: srdl2sv [-h] [-a ADDRESS_WIDTH] [-b {simple,amba3ahblite}] [-c DESCRIPTIONS]
               [-d SEARCH_PATHS [SEARCH_PATHS ...]] [-e]
               [--file-logging {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}]
               [--stdout-logging {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}] [--no-byte-enable]
               [-o OUT_DIR] [-r] [--real-tabs] [--tab-width TAB_WIDTH]
               RDL [RDL ...]

A SystemRDL 2.0 to (synthesizable) SystemVerilog compiler

positional arguments:
  RDL                   Location of RDL file(s) with root addrmap.

optional arguments:
  -h, --help            show this help message and exit
  -a ADDRESS_WIDTH, --address-width ADDRESS_WIDTH
                        Set the address width of the register space. For some protocols, the default
                        as described in the specification is used. (default: 32)
  -b {simple,amba3ahblite}, --bus {simple,amba3ahblite}
                        Set the bus protocol that shall be used by software to communicate with the
                        registers. If just a simple interface to the registers is needed, use the
                        'simple' protocol. (default: amba3ahblite)
  -c DESCRIPTIONS, --descriptions DESCRIPTIONS
                        Include descriptions of addrmaps (+16), regfiles (+8), memories (+4) registers
                        (+2), and fields (+1) in RTL. This is a bitfield.
  -d SEARCH_PATHS [SEARCH_PATHS ...], --search-paths SEARCH_PATHS [SEARCH_PATHS ...]
                        Point to one (or more) directories that will be searched for RDL files.
  -e, --no-enums        Disable enumeration generation. This will prevent the compiler from generating
                        packages and it will prevent it from using enums in the port list.
  --file-logging {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to log-file. When set to 'NONE', nothing will be
                        printed to the shell. (default: NONE)
  --stdout-logging {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to shell. When set to 'NONE', nothing will be
                        printed to the shell. (default: INFO)
  --no-byte-enable      If this flag gets set, byte-enables get disabled. At that point, it is only
                        possible to address whole registers, not single bytes within these registers
                        anymore.
  -o OUT_DIR, --out-dir OUT_DIR
                        Define output directory to dump files. If directory is non-existent, it will
                        be created. (default: ./srdl2sv_out)
  -r, --recursive-search
                        If set, the dependency directories will be searched recursively.
  --real-tabs           Use tabs, rather than spaces, for tabs
  --tab-width TAB_WIDTH
                        Define how many tabs or spaces will be contained in one level of indentation.
                        (default: 4)

Report bugs via https://github.com/Silicon1602/srdl2sv/issues
```
# Contributing
# License
The source code of srdl2sv (i.e., the actual RTL generator) is licensed under the [GPLv3](LICENSE). All templates in [srdlsv/components/templates](https://github.com/Silicon1602/srdl2sv/tree/develop/srdl2sv/components/templates) and [srdlsv/components/widgets](https://github.com/Silicon1602/srdl2sv/tree/develop/srdl2sv/components/templates) are licensed under the MIT license. Therefore, all RTL that is generated by srdl2sv is also licensed under the MIT license.

# Limitations
- [Any limitations to the systemrdl-compiler](https://systemrdl-compiler.readthedocs.io/en/latest/known_issues.html) also apply to the SystemRDL2SystemVerilog compiler.
- Depth of a hierarchy is limited to 26 levels. 
