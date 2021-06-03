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
            RegFile.templ_dict['regfile_comment']['rtl'].format(
                name = obj.inst_name,
                dimensions = self.dimensions,
                depth = self.depth),
                *self.rtl_header
            ]

        # Create generate block for register and add comment
        if self.dimensions:
            self.rtl_header.append("generate")

        for i in range(self.dimensions):
            self.rtl_header.append(
                RegFile.templ_dict['generate_for_start']['rtl'].format(
                    iterator = chr(97+i+self.parents_depths),
                    limit = self.array_dimensions[i]))

        # Empty dictionary of register objects
        # We need a dictionary since it might be required to access the objects later
        # by name (for example, in case of aliases)
        self.registers = dict()
        self.regfiles = []

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

                self.regfiles.append(
                    RegFile(
                        child,
                        self.total_array_dimensions,
                        self.total_stride,
                        config,
                        glbl_settings))
            elif isinstance(child, node.RegNode):
                if child.inst.is_alias:
                    # If the node we found is an alias, we shall not create a
                    # new register. Rather, we bury up the old register and add
                    # additional properties
                    self.logger.error('Alias registers are not implemented yet!')
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
        self.children = [
            *self.regfiles,
            *[x for x in self.registers.values()]
            ]

        self.logger.info("Done generating all child-regfiles/registers")

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


