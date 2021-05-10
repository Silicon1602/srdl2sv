import yaml
import re

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

# Local packages
from components.register import Register
from log.log import create_logger
from . import templates

# Import templates
try:
    import importlib.resources as pkg_resources
except ImportError:
    # Try backported to PY<37 `importlib_resources`.
    import importlib_resources as pkg_resources

class AddrMap:
    def __init__(self, rdlc: RDLCompiler, obj: node.RootNode, config: dict):

        self.rdlc = rdlc
        self.name = obj.inst_name

        # Create logger object
        self.logger = create_logger(
            "{}.{}".format(__name__, obj.inst_name),
            stream_log_level=config['stream_log_level'],
            file_log_level=config['file_log_level'],
            file_name=config['file_log_location'])

        self.logger.debug('Starting to process addrmap "{}"'.format(obj.inst_name))

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
                self.registers.add(Register(child, config))

        # TODO: Temporarily override RTL
        self.rtl = [x.get_rtl() for x in self.registers]

    def get_rtl(self) -> str:
        return '\n'.join(self.rtl)
