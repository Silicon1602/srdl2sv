import importlib.resources as pkg_resources
import sys
import getpass
import socket
import time
import os
import yaml

from systemrdl import node

# Local packages
from srdl2sv.components.component import Component
from srdl2sv.components.regfile import RegFile
from srdl2sv.components.register import Register
from srdl2sv.components.memory import Memory
from srdl2sv.components import templates
from srdl2sv.components import widgets


class AddrMap(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'addrmap.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, config: dict):
        super().__init__(
                    obj=obj,
                    config=config,
                    parents_strides=None,
                    parents_dimensions=None)

        # Check if global resets are defined
        glbl_settings = {}

        # Use global settings to define whether a component is already in a generate block
        glbl_settings['generate_active'] = False

        # Save whether 0, 1, or x must be set for reserved bits
        if self.obj.get_property('rsvdset'):
            glbl_settings['rsvd_val'] = "1"
        elif self.obj.get_property('rsvdsetX'):
            glbl_settings['rsvd_val'] = "x"
        else:
            glbl_settings['rsvd_val'] = "0"

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = {}
        self.regfiles = {}
        self.mems = {}
        self.regwidth = 0

        # Traverse through children
        for child in self.obj.children():
            if isinstance(child, node.AddrmapNode):
                # This addressmap opens a completely new scope. For example,
                # a field_reset does not propagate through to this scope.
                self.logger.info('Found hierarchical addrmap. Entering it...')
                self.logger.error('Child addrmaps are not implemented yet!')
            elif isinstance(child, node.RegfileNode):
                new_child = RegFile(
                                obj=child,
                                parents_dimensions=None,
                                parents_strides=None,
                                config=config,
                                glbl_settings=glbl_settings)
                self.regfiles[child.inst_name] = new_child
            elif isinstance(child, node.MemNode):
                new_child = Memory(
                                obj=child,
                                parents_dimensions=None,
                                parents_strides=None,
                                config=config,
                                glbl_settings=glbl_settings)
                new_child.sanity_checks()
                self.mems[child.inst_name] = new_child
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.registers[child.inst.alias_primary_inst.inst_name]\
                        .add_alias(child)
                else:
                    new_child = Register(
                                    obj=child,
                                    parents_dimensions=None,
                                    parents_strides=None,
                                    config=config,
                                    glbl_settings=glbl_settings)
                    self.registers[child.inst_name] = new_child

            try:
                if (regwidth := new_child.get_regwidth()) > self.regwidth:
                    self.regwidth = regwidth
            except KeyError:
                # Simply ignore nodes like SignalNodes
                pass

        self.logger.info(
            f"Detected maximum register width of whole addrmap to be '{self.regwidth}'")

        # Add registers to children. This must be done in a last step
        # to account for all possible alias combinations
        self.children = {**self.regfiles, **self.registers, **self.mems}

        self.logger.info("Done generating all child-regfiles/registers")

        # Create RTL of all registers. Registers in regfiles are
        # already built and so are memories.
        for register in self.registers.values():
            register.create_rtl()

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
        # Yay for unreadable code....
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
                name = 'srdl2sv_if'),
            '\n'
            ]

        try:
            for pkg_name in self.__get_package_names():
                import_package_list.append(
                    AddrMap.templ_dict['import_package']['rtl'].format(name = pkg_name)
                )

                import_package_list.append('\n')

        except IndexError:
            pass

        import_package_list.pop()

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

        # Add description, if applicable
        self.rtl_header.append(self.get_description())

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
        list_of_cases = []

        # Add an entry for each version of a register
        for child in self.children.values():
            for mux_entry_dim in child.create_mux_string():
                # Data structure of mux_entry:
                r2b_data = ''.join([mux_entry_dim.mux_entry.data_wire, mux_entry_dim.dim])
                r2b_rdy = ''.join([mux_entry_dim.mux_entry.rdy_wire, mux_entry_dim.dim])
                r2b_err = ''.join([mux_entry_dim.mux_entry.err_wire, mux_entry_dim.dim])
                active_wire = ''.join([mux_entry_dim.mux_entry.active_wire, mux_entry_dim.dim])

                list_of_cases.append(
                    AddrMap.templ_dict['list_of_mux_cases']['rtl'].format(
                        active_wire = active_wire,
                        r2b_data = r2b_data,
                        r2b_rdy = r2b_rdy,
                        r2b_err = r2b_err)
                    )

        # Define default case
        list_of_cases.append(AddrMap.templ_dict['default_mux_case']['rtl'])

        self.rtl_footer.append(
            self._process_yaml(
                AddrMap.templ_dict['read_mux'],
                {'list_of_cases': '\n'.join(list_of_cases)}
            )
        )

    def __add_signal_instantiation(self):
        dict_list = list(self.get_signals(True).items())
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
            pkg_resources.read_text(widgets, f"srdl2sv_{self.config['bus']}.yaml"),
            Loader=yaml.FullLoader)

        return self._process_yaml(
            self.widget_templ_dict['module_instantiation'],
            {'bus_width': self.regwidth,
             'no_byte_enable': 1 if self.config['no_byte_enable'] else 0,
            }
        )


    def __append_genvars(self):
        genvars = ', '.join([''.join(['gv_', chr(97+i)])
                    for i in range(self.get_max_dim_depth())])

        if genvars:
            genvars_instantiation = ''.join([
                '\ngenvar ',
                genvars,
                ';\n'
                ])

            self.rtl_header.append(genvars_instantiation)

    def __get_package_names(self) -> set():
        names = set()

        for register in self.registers.values():
            for typedef in register.get_typedefs().values():
                names.add(typedef.scope)

        for regfile in self.regfiles.values():
            names.update(regfile.get_package_names())

        return names

    def get_package_rtl(self, tab_width: int = 4, real_tabs = False) -> dict():
        if not self.config['enums']:
            return {}

        # First go through all registers in this scope to generate a package
        package_rtl = []
        rtl_return = {}

        # Need to keep track of enum names since they shall be unique
        # per scope
        enum_rtl = {}
        enum_rtl[self.name] = []
        enum_members = {}

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
                           f"Enum member '{var[0]}' was found at multiple locations in the same "\
                            "main scope: \n"\
                           f" -- 1st occurance: '{enum_members[var[0]]}'\n"\
                           f" -- 2nd occurance: '{'::'.join([self.name, key])}'\n\n"\
                            "This is not legal because all these enums will be defined "\
                            "in the same SystemVerilog scope. To share the same enum among "\
                            "different registers, define them on a higher level in the "\
                            "hierarchy.\n\n"\
                            "Exiting...")

                        sys.exit(1)

                    variable_list.append(
                        AddrMap.templ_dict['enum_var_list_item']['rtl'].format(
                            value = var[1],
                            width = value.width,
                            max_name_width = max_name_width,
                            name = var[0]))

                enum_rtl[self.name].append(
                    AddrMap.templ_dict['enum_declaration']['rtl'].format(
                        width=value.width-1,
                        name = key,
                        enum_var_list = ',\n'.join(variable_list)))


        # Invoke get_package_rtl method from regfiles
        for regfile in self.regfiles.values():
            for key, value in regfile.get_package_rtl().items():
                if key in enum_rtl:
                    enum_rtl[key] = [*enum_rtl[key], *value]
                else:
                    enum_rtl[key] = value

        # Create RTL to return
        for key, value in enum_rtl.items():
            if not value:
                # Skip if package wouldn't contain any enums
                continue

            package_rtl =\
                AddrMap.templ_dict['package_declaration']['rtl'].format(
                    name = key,
                    pkg_content = '\n\n'.join(value))


            rtl_return[key] = AddrMap.add_tabs(
                package_rtl,
                tab_width,
                real_tabs)

        return rtl_return
