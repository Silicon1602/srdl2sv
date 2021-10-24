import importlib.resources as pkg_resources
import sys
from typing import Optional
import yaml

from systemrdl import node

# Local packages
from srdl2sv.components.component import Component
from srdl2sv.components.register import Register
from srdl2sv.components import templates


class RegFile(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'regfile.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegfileNode,
            config: dict,
            parents_dimensions: Optional[list],
            parents_strides: Optional[list],
            glbl_settings: dict):
        super().__init__(
                    obj=obj,
                    config=config,
                    parents_strides=parents_strides,
                    parents_dimensions=parents_dimensions)

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = {}
        self.regfiles = {}

        # Set object to 0 for easy addressing
        self.obj.current_idx = [0]

        # Determine whether this regfile must add a generate block and for-loop
        if self.own_dimensions and not glbl_settings['generate_active']:
            self.generate_initiated = True
            glbl_settings['generate_active'] = True
        else:
            self.generate_initiated = False

        self.regwidth = 0

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                self.logger.fatal('Instantiating addrmaps within regfiles is not '\
                                  'supported. Addrmaps shall be instantiated at the '\
                                  'top-level of other addrmaps')
                sys.exit(1)
            elif isinstance(child, node.RegfileNode):
                self.obj.current_idx = [0]

                new_child = RegFile(
                        obj=child,
                        parents_dimensions=self.total_array_dimensions,
                        parents_strides=self.total_stride,
                        config=config,
                        glbl_settings=glbl_settings)
                self.regfiles[child.inst_name] = new_child
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.registers[child.inst.alias_primary_inst.inst_name]\
                        .add_alias(child)
                else:
                    self.obj.current_idx = [0]
                    new_child = Register(
                            obj=child,
                            parents_dimensions=self.total_array_dimensions,
                            parents_strides=self.total_stride,
                            config=config,
                            glbl_settings=glbl_settings)
                    self.registers[child.inst_name] = new_child

            try:
                if (regwidth := new_child.get_regwidth()) > self.regwidth:
                    self.regwidth = regwidth
            except KeyError:
                # Simply ignore nodes like SignalNodes
                pass

        # Add registers to children. This must be done in a last step
        # to account for all possible alias combinations
        self.children = {**self.regfiles, **self.registers}

        # Create RTL of all registers
        for register in self.registers.values():
            register.create_rtl()

        self.logger.info("Done generating all child-regfiles/registers")

        # If this regfile create a generate-block, all the register's wires must
        # be declared outside of that block
        if self.generate_initiated:
            self.rtl_header = [*self.rtl_header, *self.get_signal_instantiations_list()]
            self.rtl_header.append("")
            self.rtl_header.append("generate")

        # Add description, if applicable
        self.rtl_header = [
                self.get_description(),
                *self.rtl_header
            ]

        # Create comment and provide user information about register he/she
        # is looking at.
        self.rtl_header = [
            self._process_yaml(
                RegFile.templ_dict['regfile_comment'],
                {'name': obj.inst_name,
                 'dimensions': self.own_dimensions,
                 'depth': self.own_depth}
            ),
            *self.rtl_header
            ]

        # Create generate block for register and add comment
        for i in range(self.own_dimensions-1, -1, -1):
            self.rtl_footer.append(
                self._process_yaml(
                    RegFile.templ_dict['generate_for_end'],
                    {'dimension':  ''.join(['gv_', chr(97+i)])}
                )
            )

        for i in range(self.own_dimensions):
            self.rtl_header.append(
                self._process_yaml(
                    RegFile.templ_dict['generate_for_start'],
                    {'iterator': ''.join(['gv_', chr(97+i+self.parents_depths)]),
                     'limit': self.own_array_dimensions[i]}
                )
            )

        # End generate loop
        if self.generate_initiated:
            glbl_settings['generate_active'] = False
            self.rtl_footer.append("endgenerate")
            self.rtl_footer.append("")

    def create_mux_string(self):
        for i in self.children.values():
            yield from i.create_mux_string()

    def get_signal_instantiations_list(self) -> set():
        instantiations = []

        for child in self.children.values():
            if isinstance(child, Register):
                instantiations.append(f"\n// Variables of register '{child.name}'")
            instantiations = [*instantiations, *child.get_signal_instantiations_list()]

        return instantiations

    def get_package_names(self) -> set():
        names = set()

        for register in self.registers.values():
            for typedef in register.get_typedefs().values():
                names.add(typedef.scope)

        return names

    def get_package_rtl(self) -> {}:
        if not self.config['enums']:
            return None

        # First go through all registers in this scope to generate a package
        enum_rtl = {}

        # Need to keep track of enum names since they shall be unique
        # per scope
        enum_members = {}

        for register in self.registers.values():
            for key, value in register.get_typedefs().items():
                if value.scope not in enum_rtl:
                    enum_rtl[value.scope] = []

                variable_list = []

                max_name_width = min(
                        max([len(x[0]) for x in value.members]), 40)

                for var in value.members:
                    if var[0] not in enum_members:
                        enum_members[var[0]] = "::".join([self.name, key])
                    else:
                        self.logger.fatal(
                            "Enum member '%s' was found at multiple locations in the same "\
                            "main scope: \n"\
                            " -- 1st occurance: '%s'\n"\
                            " -- 2nd occurance: '%s'\n\n"\
                            "This is not legal because all these enums will be defined "\
                            "in the same SystemVerilog scope. To share the same enum among "\
                            "different registers, define them on a higher level in the "\
                            "hierarchy.\n\n"\
                            "Exiting...",
                            var[0],
                            enum_members[var[0]],
                            '::'.join([self.name, key])
                            )

                        sys.exit(1)

                    variable_list.append(
                        RegFile.templ_dict['enum_var_list_item']['rtl'].format(
                            value = var[1],
                            width = value.width,
                            max_name_width = max_name_width,
                            name = var[0]))

                enum_rtl[value.scope].append(
                    RegFile.templ_dict['enum_declaration']['rtl'].format(
                        width=value.width-1,
                        name = key,
                        enum_var_list = ',\n'.join(variable_list)))

        return enum_rtl
