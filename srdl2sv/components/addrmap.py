import re
import importlib.resources as pkg_resources
import yaml

from systemrdl import node
from systemrdl.node import FieldNode

# Local packages
from components.component import Component
from components.regfile import RegFile
from components.register import Register
from . import templates


class AddrMap(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'addrmap.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, config: dict):
        super().__init__(obj, config)

        # Create logger object
        self.create_logger(self.path, config)
        self.logger.debug('Starting to process addrmap')

        # Check if global resets are defined
        glbl_settings = dict()

        (glbl_settings['field_reset'], glbl_settings['cpuif_reset']) = \
            self.__process_global_resets()

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                # This addressmap opens a completely new scope. For example,
                # a field_reset does not propagate through to this scope.
                self.logger.info('Found hierarchical addrmap. Entering it...')
                self.logger.error('Child addrmaps are not implemented yet!')
            elif isinstance(child, node.RegfileNode):
                self.children.append(RegFile(child, [], [], config, glbl_settings))
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.logger.error('Alias registers are not implemented yet!')
                else:
                    self.registers[child.inst_name] = \
                        Register(child, [], [], config, glbl_settings)

        # Add registers to children. This must be done in a last step
        # to account for all possible alias combinations
        self.children = [
            *self.children,
            *[x for x in self.registers.values()]
            ]

        self.logger.info("Done generating all child-regfiles/registers")

        # Start assembling addrmap module
        self.logger.info("Starting to assemble input & output ports")

        # Reset ports
        reset_ports_rtl = [
            AddrMap.templ_dict['reset_port'].format(
                name = name)
            for name in [x for x in self.get_resets()]
            ]

        # Prefetch dictionaries in local array
        input_dict_list = [(key, value) for (key, value) in self.get_ports('input').items()]
        output_dict_list = [(key, value) for (key, value) in self.get_ports('output').items()]

        input_signal_width = min(
                max([len(value[0]) for (_, value) in input_dict_list]), 40)

        input_name_width = min(
                max([len(key) for (key, _) in input_dict_list]), 40)

        output_signal_width = min(
                 max([len(value[0]) for (_, value) in output_dict_list]), 40)

        output_name_width = min(
                max([len(key) for (key, _) in output_dict_list]), 40)


        # Input ports
        input_ports_rtl = [
            AddrMap.templ_dict['input_port'].format(
                name = key,
                signal_type = value[0],
                signal_width = input_signal_width,
                name_width = input_name_width,
                unpacked_dim = '[{}]'.format(
                    ']['.join(
                        [str(y) for y in value[1]]))
                    if value[1] else '')
            for (key, value) in input_dict_list
            ]

        # Output ports
        output_ports_rtl = [
            AddrMap.templ_dict['output_port'].format(
                name = key,
                signal_width = output_signal_width,
                name_width = output_name_width,
                signal_type = value[0],
                unpacked_dim = '[{}]'.format(
                    ']['.join(
                        [str(y) for y in value[1]]))
                    if value[1] else '')
            for (key, value) in output_dict_list
            ]

        # Remove comma from last port entry
        output_ports_rtl[-1] = output_ports_rtl[-1].rstrip(',')

        self.rtl_header.append(
            AddrMap.templ_dict['module_declaration'].format(
                name = self.name,
                resets = '\n'.join(reset_ports_rtl),
                inputs = '\n'.join(input_ports_rtl),
                outputs = '\n'.join(output_ports_rtl)))

    def __process_global_resets(self):
        field_reset_list = \
            [x for x in self.obj.signals() if x.get_property('field_reset')]
        cpuif_reset_list = \
            [x for x in self.obj.signals() if x.get_property('cpuif_reset')]

        if field_reset_list:
            rst_name = field_reset_list[0].inst_name
            self.logger.info("Found field_reset signal '{}'".format(rst_name))

            # Save to set to generate input
            self.resets.add(rst_name)

            # Save position 0 of list
            field_reset_item = field_reset_list[0]
        else:
            field_reset_item = None

        if cpuif_reset_list:
            rst_name = cpuif_reset_list[0].inst_name
            self.logger.info("Found cpuif_reset signal '{}'".format(rst_name))

            # Save to set to generate input
            self.resets.add(rst_name)

            # Save position 0 of list
            cpuif_reset_item = cpuif_reset_list[0]
        else:
            cpuif_reset_item = None

        # Method is only called once on a global level. Otherwise, process_reset_signal
        # is called several times to calculate the dictionary, although it will always
        # return the same result.
        field_reset = AddrMap.process_reset_signal(field_reset_item)
        cpuif_reset = AddrMap.process_reset_signal(cpuif_reset_item)

        return (field_reset, cpuif_reset)


