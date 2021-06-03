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

        # Use global settings to define whether a component is already in a generate block
        glbl_settings['generate_active'] = False

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()
        self.regfiles = []

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                # This addressmap opens a completely new scope. For example,
                # a field_reset does not propagate through to this scope.
                self.logger.info('Found hierarchical addrmap. Entering it...')
                self.logger.error('Child addrmaps are not implemented yet!')
            elif isinstance(child, node.RegfileNode):
                self.regfiles.append(RegFile(child, [], [], config, glbl_settings))
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
            *self.regfiles,
            *[x for x in self.registers.values()]
            ]

        self.logger.info("Done generating all child-regfiles/registers")

        # Start assembling addrmap module
        self.logger.info("Starting to assemble input & output ports")

        # Reset ports
        reset_ports_rtl = [
            AddrMap.templ_dict['reset_port']['rtl'].format(
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
            AddrMap.templ_dict['input_port']['rtl'].format(
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
            AddrMap.templ_dict['output_port']['rtl'].format(
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

        import_package_list = []
        [import_package_list.append(
            AddrMap.templ_dict['import_package']['rtl'].format(
                name = self.name)) for x in self.get_package_names()]

        self.rtl_header.append(
            AddrMap.templ_dict['module_declaration']['rtl'].format(
                name = self.name,
                import_package_list = ',\n'.join(import_package_list),
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

    def get_package_names(self) -> set():
        names = set()

        for i in self.registers.values():
            for key, value in i.get_typedefs().items():
                names.add(value.scope)

        return names

    def get_package_rtl(self, tab_width: int = 4, real_tabs = False) -> dict():
        # First go through all registers in this scope to generate a package
        package_rtl = []
        enum_rtl = []
        rtl_return = dict()

        for i in self.registers.values():
            for key, value in i.get_typedefs().items():
                variable_list = []

                max_name_width = min(
                        max([len(x[0]) for x in value.members]), 40)

                for var in value.members:
                    variable_list.append(
                        AddrMap.templ_dict['enum_var_list_item']['rtl'].format(
                            value = var[1],
                            width = value.width,
                            max_name_width = max_name_width,
                            name = var[0]))

                enum_rtl.append(
                    AddrMap.templ_dict['enum_declaration']['rtl'].format(
                        width=value.width-1,
                        name = key,
                        enum_var_list = ',\n'.join(variable_list)))

        package_rtl =\
            AddrMap.templ_dict['package_declaration']['rtl'].format(
                name = self.name,
                pkg_content = '\n\n'.join(enum_rtl))


        rtl_return[self.name] = AddrMap.add_tabs(
            package_rtl,
            tab_width,
            real_tabs)

        # TODO Later, request get_package_rtl()-method of all child regfiles

        return rtl_return


