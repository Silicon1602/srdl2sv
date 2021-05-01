#!/usr/bin/env python3

import sys
import os
import re
import time

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

from components.addrmap import AddrMap


if __name__ == "__main__":
    # Take start timestamp
    start = time.time()

    # Compile and elaborate files provided from the command line
    input_files = sys.argv[1:]
    rdlc = RDLCompiler()

    try:
        for input_file in input_files:
            rdlc.compile_file(input_file)

        root = rdlc.elaborate()
    except RDLCompileError:
        sys.exit(1)

    addrmap = AddrMap(rdlc, root.top)

    print("====================================================")
    print("Elapsed time: {} seconds".format(time.time() - start))
    print("====================================================")


