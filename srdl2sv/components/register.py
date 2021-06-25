import importlib.resources as pkg_resources
import math
import sys
import yaml
import itertools

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
        self.__process_variables(obj, parents_dimensions, parents_stride, glbl_settings)

        # Create RTL for fields of initial, non-alias register
        for field in obj.fields():
            # Use range to save field in an array. Reason is, names are allowed to
            # change when using an alias
            field_range = ':'.join(map(str, [field.msb, field.lsb]))

            self.children[field_range] = Field(field,
                                               self.total_array_dimensions,
                                               config,
                                               glbl_settings)

            if not config['disable_sanity']:
                self.children[field_range].sanity_checks()

    def create_rtl(self):
        # Create RTL of children
        [x.create_rtl() for x in self.children.values()]

        # Create generate block for register and add comment
        if self.dimensions and not self.generate_active:
            self.rtl_header.append("generate")

        # Add N layers of for-loop starts
        for i in range(self.dimensions):
            self.rtl_header.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = chr(97+i+self.parents_depths),
                    limit = self.array_dimensions[i]))

        # Add decoders for all registers & aliases
        self.__add_address_decoder()

        # Fields will be added by get_rtl()

        # Add N layers of for-loop end
        for i in range(self.dimensions-1, -1, -1):
            self.rtl_footer.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = chr(97+i)))

        if self.dimensions and not self.generate_active:
            self.rtl_footer.append("endgenerate\n")

        # Add assignment of read-wires
        self.__add_sw_read_assignments()

        # Add wire instantiation
        if not self.generate_active:
            # We can/should only do this if there is no encapsulating 
            # regfile which create a generate
            self.__add_signal_instantiations()

        # Create comment and provide user information about register he/she is looking at
        self.rtl_header = [
            Register.templ_dict['reg_comment'].format(
                name = self.obj.inst_name,
                dimensions = self.dimensions,
                depth = self.depth),
                *self.rtl_header
            ]

    def __add_sw_read_assignments(self):
        accesswidth = self.obj.get_property('accesswidth') - 1
        self.rtl_footer.append("")

        for x in self.name_addr_mappings:
            current_bit = 0
            list_of_fields = []
            for y in self.children.values():
                if x[0] in y.readable_by:
                    empty_bits = y.lsb - current_bit
                    current_bit = y.msb + 1

                    if empty_bits > 0:
                        list_of_fields.append("{}'b0".format(empty_bits))

                    list_of_fields.append("{}_q".format(y.path_underscored))

            empty_bits = accesswidth - current_bit + 1

            if empty_bits > 0:
                list_of_fields.append("{}'b0".format(empty_bits))

            # Create list of mux-inputs to later be picked up by carrying addrmap
            self.sw_read_assignment_var_name.append(
                (
                    self.process_yaml(
                        Register.templ_dict['sw_read_assignment_var_name'],
                        {'path': x[0],
                         'accesswidth': accesswidth}
                    ),
                    x[1], # Start addr
                )
            )

            self.rtl_footer.append(
                self.process_yaml(
                    Register.templ_dict['sw_read_assignment'],
                    {'sw_read_assignment_var_name': self.sw_read_assignment_var_name[-1][0],
                     'genvars': self.genvars_str,
                     'list_of_fields': ', '.join(reversed(list_of_fields))}
                )
            )

    def create_mux_string(self):
        for mux_tuple in self.sw_read_assignment_var_name:
            # Loop through lowest dimension and add stride of higher
            # dimension once everything is processed
            if self.total_array_dimensions:
                vec = [0]*len(self.total_array_dimensions)

                for i in self.eval_genvars(vec, 0, self.total_array_dimensions):
                    yield (mux_tuple, i)
            else:
                yield(mux_tuple, (mux_tuple[1], ''))

    def eval_genvars(self, vec, depth, dimensions):
        for i in range(dimensions[depth]):
            vec[depth] = i

            if depth == len(dimensions) - 1:
                yield (
                        eval(self.genvars_sum_str_vectorized),
                        '[{}]'.format(']['.join(map(str, vec)))
                      )
            else:
                yield from self.eval_genvars(vec, depth+1, dimensions)


        vec[depth] = 0

    def __add_address_decoder(self):
        # Assign variables from bus
        self.obj.current_idx = [0]

        if self.total_dimensions:
            rw_wire_assign_field = 'rw_wire_assign_multi_dim'
        else:
            rw_wire_assign_field = 'rw_wire_assign_1_dim'

        [self.rtl_header.append(
            self.process_yaml(
                Register.templ_dict[rw_wire_assign_field],
                {'path': x[0],
                 'addr': x[1],
                 'alias': '(alias)' if i > 0 else '',
                 'genvars': self.genvars_str,
                 'genvars_sum': self.genvars_sum_str,
                 'depth': self.depth,
                 'field_type': self.field_type}
            )
        ) for i, x in enumerate(self.name_addr_mappings)]

    def __add_signal_instantiations(self):
        # Add wire/register instantiations
        self.rtl_header = [
                *self.get_signal_instantiations_list(),
                '',
                *self.rtl_header
            ]

    def get_signal_instantiations_list(self):
        dict_list = [(key, value) for (key, value) in self.get_signals().items()]

        signal_width = min(max([len(value[0]) for (_, value) in dict_list]), 40)

        name_width = min(max([len(key) for (key, _) in dict_list]), 40)

        return [Register.templ_dict['signal_declaration'].format(
                   name = key,
                   type = value[0],
                   signal_width = signal_width,
                   name_width = name_width,
                   unpacked_dim = '[{}]'.format(
                       ']['.join(
                           [str(y) for y in value[1]]))
                       if value[1] else '')
               for (key, value) in dict_list]

    def add_alias(self, obj: node.RegNode):
        for field in obj.fields():
            # Use range to save field in an array. Reason is, names are allowed to
            # change when using an alias
            field_range = ':'.join(map(str, [field.msb, field.lsb]))

            try:
                self.children[field_range].add_sw_access(field, alias=True)
            except KeyError:
                self.logger.fatal("Range of field '{}' in alias register '{}' does "
                                  "not correspond to range of field in original "
                                  "register '{}'. This is illegal according to 10.5.1 b)"
                                  "of the SystemRDL 2.0 LRM.". format(
                                      field.inst_name,
                                      obj.inst_name,
                                      self.name))
                sys.exit(1)

        # Add name to list
        self.obj.current_idx = [0]
        self.name_addr_mappings.append(
            (self.create_underscored_path_static(obj)[3], obj.absolute_address))

    def __process_variables(
            self,
            obj: node.RegNode,
            parents_dimensions: list,
            parents_stride: list,
            glbl_settings: dict):

        # Save name
        self.obj.current_idx = [0]
        self.name = obj.inst_name

        # Create mapping between (alias-) name and address
        self.name_addr_mappings = [
            (self.create_underscored_path_static(obj)[3], obj.absolute_address)
            ]

        # Create full name
        self.create_underscored_path()

        # Gnerate already started?
        self.generate_active = glbl_settings['generate_active']

        # Empty array for mux-input signals
        self.sw_read_assignment_var_name = []

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
        genvars = ['[{}]'.format(chr(97+i)) for i in range(self.total_dimensions)]
        self.genvars_str = ''.join(genvars)

        # Determine value to compare address with
        genvars_sum = []
        genvars_sum_vectorized = []
        try:
            for i, stride in enumerate(self.total_stride):
                genvars_sum.append(chr(97+i))
                genvars_sum.append("*")
                genvars_sum.append(str(stride))
                genvars_sum.append("+")

                genvars_sum_vectorized.append('vec[')
                genvars_sum_vectorized.append(str(i))
                genvars_sum_vectorized.append(']*')
                genvars_sum_vectorized.append(str(stride))
                genvars_sum_vectorized.append("+")

            genvars_sum.pop()
            genvars_sum_vectorized.pop()

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
        self.genvars_sum_str_vectorized = ''.join(genvars_sum_vectorized)

