import re
import importlib.resources as pkg_resources
import sys
import math
import yaml

from systemrdl import node
from systemrdl.node import FieldNode

# Local packages
from components.component import Component
from components.register import Register
from . import templates


class RegFile(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'regfile.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegfileNode,
            parents_dimensions: list,
            parents_stride: list,
            config: dict, 
            glbl_settings: dict):
        super().__init__(obj, config)

        # Save and/or process important variables
        self.__process_variables(obj, parents_dimensions, parents_stride)

        # Create comment and provide user information about register he/she
        # is looking at.
        self.rtl_header = [
            self.process_yaml(
                RegFile.templ_dict['regfile_comment'],
                {'name': obj.inst_name,
                 'dimensions': self.dimensions,
                 'depth': self.depth}
            ),
            *self.rtl_header
            ]

        # Create generate block for register and add comment
        for i in range(self.dimensions-1, -1, -1):
            self.rtl_footer.append(
                self.process_yaml(
                    RegFile.templ_dict['generate_for_end'],
                    {'dimension':  chr(97+i)}
                )
            )

        if self.dimensions and not glbl_settings['generate_active']:
            self.rtl_header.append("generate")
            self.generate_initiated = True
            glbl_settings['generate_active'] = True
        else:
            self.generate_initiated = False

        for i in range(self.dimensions):
            self.rtl_header.append(
                self.process_yaml(
                    RegFile.templ_dict['generate_for_start'],
                    {'iterator': chr(97+i+self.parents_depths),
                     'limit': self.array_dimensions[i]}
                )
            )

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()
        self.regfiles = dict()

        # Set object to 0 for easy addressing
        self.obj.current_idx = [0]

        # Traverse through children
        for child in obj.children():
            if isinstance(child, node.AddrmapNode):
                self.logger.fatal('Instantiating addrmaps within regfiles is not '\
                                  'supported. Addrmaps shall be instantiated at the '\
                                  'top-level of other addrmaps')
                sys.exit(1)
            elif isinstance(child, node.RegfileNode):
                self.obj.current_idx = [0]

                self.regfiles[child.inst_name] = \
                    RegFile(
                        child,
                        self.total_array_dimensions,
                        self.total_stride,
                        config,
                        glbl_settings)
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.registers[child.inst.alias_primary_inst.inst_name]\
                        .add_alias(child)
                else:
                    self.obj.current_idx = [0]
                    self.registers[child.inst_name] = \
                        Register(
                            child,
                            self.total_array_dimensions,
                            self.total_stride,
                            config,
                            glbl_settings)

        # Add registers to children. This must be done in a last step
        # to account for all possible alias combinations
        self.children = {**self.regfiles, **self.registers}

        self.logger.info("Done generating all child-regfiles/registers")

        # End generate loop
        if self.generate_initiated:
            glbl_settings['generate_active'] = False
            self.rtl_footer.append("endgenerate")

        # Create RTL of all registers
        [x.create_rtl() for x in self.registers.values()]

    def __process_variables(self,
            obj: node.RegfileNode,
            parents_dimensions: list,
            parents_stride: list):

        # Determine dimensions of register
        if obj.is_array:
            self.sel_arr = 'array'
            self.total_array_dimensions = [*parents_dimensions, *self.obj.array_dimensions]
            self.array_dimensions = self.obj.array_dimensions

            # Merge parent's stride with stride of this regfile. Before doing so, the
            # respective stride of the different dimensions shall be calculated
            self.total_stride = [
                *parents_stride, 
                *[math.prod(self.array_dimensions[i+1:])
                    *self.obj.array_stride
                        for i, _ in enumerate(self.array_dimensions)]
                ]
        else:
            self.sel_arr = 'single'
            self.total_array_dimensions = parents_dimensions
            self.array_dimensions = []
            self.total_stride = parents_stride

        # How many dimensions were already part of some higher up hierarchy?
        self.parents_depths = len(parents_dimensions)

        self.total_depth = '[{}]'.format(']['.join(f"{i}" for i in self.total_array_dimensions))
        self.total_dimensions = len(self.total_array_dimensions)

        self.depth = '[{}]'.format(']['.join(f"{i}" for i in self.array_dimensions))
        self.dimensions = len(self.array_dimensions)

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(self.dimensions)]
        self.genvars_str = ''.join(genvars)

    def create_mux_string(self):
        for i in self.children.values():
            yield from i.create_mux_string()

