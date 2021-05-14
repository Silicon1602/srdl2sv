import re
import importlib.resources as pkg_resources
import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

# Local packages
from components.component import Component
from components.register import Register
from log.log import create_logger
from . import templates


class AddrMap(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'addrmap.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, config: dict):
        super().__init__()

        # Save and/or process important variables
        self.__process_variables(obj)

        # Create logger object
        self.create_logger(self.path, config)
        self.logger.debug('Starting to process addrmap')

        template = pkg_resources.read_text(templates, 'addrmap.sv')

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                self.logger.info('Found hierarchical addrmap. Entering it...')
                self.logger.error('Child addrmaps are not implemented yet!')
            elif isinstance(child, node.RegfileNode):
                self.logger.error('Regfiles are not implemented yet!')
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.logger.error('Alias registers are not implemented yet!')
                else:
                    self.registers[child.inst_name] = Register(child, config)

        # Add regfiles and registers to children
        self.children = [x for x in self.registers.values()]

        self.logger.info("Done generating all child-regfiles/registers")

        # Start assembling addrmap module
        self.logger.info("Starting to assemble input/output/inout ports")

        # Inout port
        inout_ports_rtl = [
            AddrMap.templ_dict['inout_port'].format(
                name = x) for x in self.get_ports('inout')]
        # Input ports
        input_ports_rtl = [
            AddrMap.templ_dict['input_port'].format(
                name = x) for x in self.get_ports('input')]
        # Output ports
        output_ports_rtl = [
            AddrMap.templ_dict['output_port'].format(
                name = x) for x in self.get_ports('output')]

        # Remove comma from last port entry
        output_ports_rtl[-1] = output_ports_rtl[-1].rstrip(',')

        self.rtl_header.append(
            AddrMap.templ_dict['module_declaration'].format(
                name = obj.inst_name,
                inouts = '\n'.join(inout_ports_rtl),
                inputs = '\n'.join(input_ports_rtl),
                outputs = '\n'.join(output_ports_rtl)))





    def __process_variables(self, obj: node.RootNode):
        # Save object
        self.obj = obj

        # Create full name
        self.owning_addrmap = obj.owning_addrmap.inst_name
        self.path = obj.get_path()\
                        .replace('[]', '')\
                        .replace('{}.'.format(self.owning_addrmap), '')

        self.path_underscored = self.path.replace('.', '_')

        self.name = obj.inst_name
