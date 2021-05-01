import yaml
import re

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode


# Local packages
from components.register import Register
from . import templates

# Import templates
try:
    import importlib.resources as pkg_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources as pkg_resources

class AddrMap:
    def __init__(self, rdlc: RDLCompiler, obj: node.RootNode):

        self.rdlc = rdlc

        template = pkg_resources.read_text(templates, 'addrmap.sv')

        # Read template for SystemVerilog module
        tmpl_addrmap = re.compile("{addrmap_name}")
        self.rtl = tmpl_addrmap.sub(obj.inst_name, template)

        # Empty list of register logic
        self.registers = set()

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                pass
            elif isinstance(child, node.RegfileNode):
                pass
            elif isinstance(child, node.RegNode):
                self.registers.add(Register(child))

        for i in self.registers:
            print("\n\n")
            for j in i.rtl:
                print(j)

    def get_rtl(self) -> str:
        return '\n'.join(self.rtl)
