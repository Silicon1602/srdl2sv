![srdl2sv logo](images/srdl2sv_logo.gif)
# Introduction 
srdl2sv is a [SystemRDL 2.0](https://www.accellera.org/images/downloads/standards/systemrdl/SystemRDL_2.0_Jan2018.pdf) to (synthesizable) [SystemVerilog](https://ieeexplore.ieee.org/document/8299595/versions) compiler. The tool is based on based on [SystemRDL/systemrdl-compiler](https://github.com/SystemRDL/systemrdl-compiler). 
## ⚠️ Non-production ready
Warning! This software is still under development and not yet ready for use in production. 
# Getting started
## Installation
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
## Using the generated RTL

## Help function
A comprehensive help function of the tool can be invoked by running `srdl2sv --help`.
```
usage: main.py [-h] [-o OUT_DIR] [-d SEARCH_PATHS [SEARCH_PATHS ...]] [-r] [-x] [--stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}] [--file_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}]
               [--real_tabs] [--tab_width TAB_WIDTH]
               IN_RDL [IN_RDL ...]

SystemRDL 2 SystemVerilog compiler

positional arguments:
  IN_RDL                Location of RDL file(s) with root addrmap.

optional arguments:
  -h, --help            show this help message and exit
  -o OUT_DIR, --out_dir OUT_DIR
                        Define output directory to dump files. If directory is non-existent, it will be created. (default: ./srdl2sv_out)
  -d SEARCH_PATHS [SEARCH_PATHS ...], --search_paths SEARCH_PATHS [SEARCH_PATHS ...]
                        Point to one (or more) directories that will be searched for RDL files.
  -r, --recursive_search
                        If set, the dependency directories will be searched recursively.
  -x, --disable_sanity  Disable sanity checks or components. This might speed up the compiler but is generally not recommended!
  --stream_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to shell. When set to 'NONE', nothing will be printed to the shell. (default: WARNING)
  --file_log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL,NONE}
                        Set verbosity level of output to log-file. When set to 'NONE', nothing will be printed to the shell. (default: INFO)
  --real_tabs           Use tabs, rather than spaces, for tabs
  --tab_width TAB_WIDTH
                        Define how many tabs or spaces will be contained in one level of indentation. (default: 4)
```
# Contributing
# Limitations
- [Any limitations to the systemrdl-compiler](https://systemrdl-compiler.readthedocs.io/en/latest/known_issues.html) also apply to the SystemRDL2SystemVerilog compiler.
- Depth of a hierarchy is limited to 26 levels. 
