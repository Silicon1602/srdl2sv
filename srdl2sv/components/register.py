import importlib.resources as pkg_resources
import yaml
import math

from systemrdl import node

# Local modules
from components.component import Component
from components.field import Field
from . import templates

class Register(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'regs.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegNode,
            parents_dimensions: list,
            parents_stride: list,
            config: dict,
            glbl_settings: dict):
        super().__init__(obj, config)

        # Save and/or process important variables
        self.__process_variables(obj, parents_dimensions, parents_stride)

        # Create RTL for fields
        # Fields should be in order in RTL,therefore, use list
        for field in obj.fields():
            field_obj = Field(field, self.total_array_dimensions, config, glbl_settings)

            if not config['disable_sanity']:
                field_obj.sanity_checks()

            self.children.append(field_obj)

        # Create generate block for register and add comment
        if self.dimensions and not glbl_settings['generate_active']:
            self.rtl_header.append("generate")
            glbl_settings['generate_active'] = True
            self.generate_initiated = True
        else:
            self.generate_initiated = False

        for i in range(self.dimensions):
            self.rtl_header.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = chr(97+i+self.parents_depths),
                    limit = self.array_dimensions[i]))


        # End loops
        for i in range(self.dimensions-1, -1, -1):
            self.rtl_footer.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = chr(97+i)))

        if self.generate_initiated:
            glbl_settings['generate_active'] = False
            self.rtl_footer.append("endgenerate")

        # Assign variables from bus
        self.obj.current_idx = [0]

        if self.dimensions:
            rw_wire_assign_field = 'rw_wire_assign_multi_dim'
        else:
            rw_wire_assign_field = 'rw_wire_assign_1_dim'

        self.rtl_header.append(
            Register.templ_dict[rw_wire_assign_field]['rtl'].format(
                path = self.path_underscored,
                addr = self.obj.absolute_address,
                genvars = self.genvars_str,
                genvars_sum =self.genvars_sum_str,
                depth = self.depth))

        self.yaml_signals_to_list(Register.templ_dict[rw_wire_assign_field])

        # Add wire/register instantiations
        dict_list = [(key, value) for (key, value) in self.get_signals().items()]

        signal_width = min(max([len(value[0]) for (_, value) in dict_list]), 40)

        name_width = min(max([len(key) for (key, _) in dict_list]), 40)

        self.rtl_header = [
            *[
                Register.templ_dict['signal_declaration'].format(
                    name = key,
                    type = value[0],
                    signal_width = signal_width,
                    name_width = name_width,
                    unpacked_dim = '[{}]'.format(
                        ']['.join(
                            [str(y) for y in value[1]]))
                        if value[1] else '')
                for (key, value) in dict_list],
                '',
                *self.rtl_header,
            ]

        # Create comment and provide user information about register he/she
        # is looking at.
        self.rtl_header = [
            Register.templ_dict['reg_comment'].format(
                name = obj.inst_name,
                dimensions = self.dimensions,
                depth = self.depth),
                *self.rtl_header
            ]


    def __process_variables(
            self,
            obj: node.RegNode,
            parents_dimensions: list,
            parents_stride: list):
        # Save object
        self.obj = obj

        # Save name
        self.name = obj.inst_name

        # Create full name
        self.create_underscored_path()

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
            self.total_stride = self.obj.array_stride

        # How many dimensions were already part of some higher up hierarchy?
        self.parents_depths = len(parents_dimensions)

        self.total_depth = '[{}]'.format(']['.join(f"{i}" for i in self.total_array_dimensions))
        self.total_dimensions = len(self.total_array_dimensions)

        self.depth = '[{}]'.format(']['.join(f"{i}" for i in self.array_dimensions))
        self.dimensions = len(self.array_dimensions)

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(self.total_dimensions)]
        self.genvars_str = ''.join(genvars)

        # Determine value to compare address with
        genvars_sum = []
        try:
            for i, stride in enumerate(self.total_stride):
                genvars_sum.append(chr(97+i))
                genvars_sum.append("*")
                genvars_sum.append(str(stride))
                genvars_sum.append("+")

            genvars_sum.pop()

            self.logger.debug(
                "Multidimensional with dimensions '{}' and stride '{}'".format(
                    self.total_array_dimensions,
                    self.total_stride))
        except TypeError:
            self.logger.debug(
                "Caught expected TypeError because self.total_stride is empty")
        except IndexError:
            self.logger.debug(
                "Caugt expected IndexError because genvars_sum is empty")

        self.genvars_sum_str = ''.join(genvars_sum)

