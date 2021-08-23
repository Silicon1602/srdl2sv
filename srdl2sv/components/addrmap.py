import re
import importlib.resources as pkg_resources
import sys
import yaml

from systemrdl import node

# Local packages
from components.component import Component
from components.regfile import RegFile
from components.register import Register
from . import templates
from . import widgets


class AddrMap(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'addrmap.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, config: dict):
        super().__init__(obj, config)

        # Check if global resets are defined
        glbl_settings = dict()

        # Set defaults so that some of the common component methods work
        self.total_dimensions = 0
        self.total_array_dimensions = []

        # Use global settings to define whether a component is already in a generate block
        glbl_settings['generate_active'] = False

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()
        self.regfiles = dict()

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                # This addressmap opens a completely new scope. For example,
                # a field_reset does not propagate through to this scope.
                self.logger.info('Found hierarchical addrmap. Entering it...')
                self.logger.error('Child addrmaps are not implemented yet!')
            elif isinstance(child, node.RegfileNode):
                self.regfiles[child.inst_name] = \
                    RegFile(child, [], [], config, glbl_settings)
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.registers[child.inst.alias_primary_inst.inst_name]\
                        .add_alias(child)
                else:
                    self.registers[child.inst_name] = \
                        Register(child, [], [], config, glbl_settings)

        # Add registers to children. This must be done in a last step
        # to account for all possible alias combinations
        self.children = {**self.regfiles, **self.registers}

        self.logger.info("Done generating all child-regfiles/registers")

        # Create RTL of all registers. Registers in regfiles are
        # already built.
        [x.create_rtl() for x in self.registers.values()]

        # Add bus widget ports
        widget_rtl = self.__get_widget_ports_rtl()

        # Start assembling addrmap module
        self.logger.info("Starting to assemble input & output ports")

        # Reset ports
        reset_ports_rtl = [
            AddrMap.templ_dict['reset_port']['rtl'].format(
                name = name)
            for name in self.get_resets()
            ]

        # Prefetch dictionaries in local array
        input_dict_list = self.get_ports('input').items()
        output_dict_list = self.get_ports('output').items()

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

        # Define packages to be included. Always include the
        # b2w and w2b defines.
        import_package_list = [
            AddrMap.templ_dict['import_package']['rtl'].format(
                name = 'srdl2sv_widget'),
            '\n'
            ]

        try:
            for x in self.get_package_names():
                import_package_list.append(
                    AddrMap.templ_dict['import_package']['rtl'].format(name = x)
                )

                import_package_list.append('\n')

        except IndexError:
            pass

        import_package_list.pop()
        
        import getpass
        import socket
        import time
        import os

        self.rtl_header.append(
            AddrMap.templ_dict['header'].format(
                user = getpass.getuser(),
                time = time.strftime('%B %d %Y %H:%M:%S', config['ts']),
                year = time.strftime('%Y', config['ts']),
                version = config['version'],
                path = os.getcwd(),
                rdl_file = config['input_file'],
                incdirs = '\n *  - '.join(config['search_paths']),
                config = '\n *  - '.join(config['list_args']),
                addrmap = self.name.upper(),
                host = socket.gethostname()))

        self.rtl_header.append(
            AddrMap.templ_dict['module_declaration']['rtl'].format(
                name = self.name,
                import_package_list = ''.join(import_package_list),
                resets = '\n'.join(reset_ports_rtl),
                inputs = '\n'.join(input_ports_rtl),
                outputs = '\n'.join(output_ports_rtl)))

        # Add wire/register instantiations
        self.__add_signal_instantiation()

        # Add bus widget RTL
        self.rtl_header.append(widget_rtl)

        # Append genvars
        self.__append_genvars()

        # Create read multiplexer
        self.__create_mux_string()

        # Add endmodule keyword
        self.rtl_footer.append('endmodule')

    def __create_mux_string(self):
        # TODO: Add variable for bus width
        self.rtl_footer.append(
            self.process_yaml(
                AddrMap.templ_dict['read_mux'],
                {'list_of_cases':
                    '\n'.join([
                        AddrMap.templ_dict['default_mux_case']['rtl'],
                        *[AddrMap.templ_dict['list_of_mux_cases']['rtl']
                            .format(x[0][1]+x[1][0],
                                    ''.join(
                                        [x[0][0],
                                         x[1][1]])) for y in self.children.values() \
                                                        for x in y.create_mux_string()
                        ]
                    ])
                }
            )
        )

    def __add_signal_instantiation(self):
        dict_list = [(key, value) for (key, value) in self.get_signals(True).items()]
        signal_width = min(max([len(value[0]) for (_, value) in dict_list]), 40)
        name_width = min(max([len(key) for (key, _) in dict_list]), 40)

        self.rtl_header = [
            *self.rtl_header,
            '',
            '// Internal signals',
            *[AddrMap.templ_dict['signal_declaration'].format(
                name = key,
                type = value[0],
                signal_width = signal_width,
                name_width = name_width,
                unpacked_dim = '[{}]'.format(
                    ']['.join(
                        [str(y) for y in value[1]]))
                    if value[1] else '')
                for (key, value) in dict_list],
            ''
            ]

    def __get_widget_ports_rtl(self):
        self.widget_templ_dict = yaml.load(
            pkg_resources.read_text(widgets, '{}.yaml'.format(self.config['bus'])),
            Loader=yaml.FullLoader)

        return self.process_yaml(
            self.widget_templ_dict['module_instantiation'],
            # TODO: Add widths
        )


    def __append_genvars(self):
        genvars = ''.join([
            '\ngenvar ',
            ', '.join([chr(97+i) for i in range(self.get_max_dim_depth())]),
            ';\n'
            ])

        self.rtl_header.append(genvars)

    def get_package_names(self) -> set():
        names = set()

        for i in self.registers.values():
            for x in i.get_typedefs().values():
                names.add(x.scope)

        [names.update(x.get_package_names()) for x in self.regfiles.values()]

        return names

    def get_package_rtl(self, tab_width: int = 4, real_tabs = False) -> dict():
        if not self.config['enums']:
            return dict()

        # First go through all registers in this scope to generate a package
        package_rtl = []
        enum_rtl = []
        rtl_return = dict()

        # Need to keep track of enum names since they shall be unique
        # per scope
        enum_members = dict()

        for i in self.registers.values():
            for key, value in i.get_typedefs().items():
                variable_list = []

                max_name_width = min(
                        max([len(x[0]) for x in value.members]), 40)

                for var in value.members:
                    if var[0] not in enum_members:
                        enum_members[var[0]] = "::".join([self.name, key])
                    else:
                        self.logger.fatal(
                            "Enum member '{}' was found at multiple locations in the same "\
                            "main scope: \n"\
                            " -- 1st occurance: '{}'\n"\
                            " -- 2nd occurance: '{}'\n\n"\
                            "This is not legal because all these enums will be defined "\
                            "in the same SystemVerilog scope. To share the same enum among "\
                            "different registers, define them on a higher level in the "\
                            "hierarchy.\n\n"\
                            "Exiting...".format(
                                var[0],
                                enum_members[var[0]],
                                "::".join([self.name, key])))

                        sys.exit(1)

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

        # Invoke get_package_rtl method from regfiles
        [rtl_return.update(x.get_package_rtl(tab_width, real_tabs))
            for x in self.regfiles.values()]

        return rtl_return


