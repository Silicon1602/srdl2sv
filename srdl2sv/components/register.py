import importlib.resources as pkg_resources
import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

# Local modules
from components.component import Component
from components.field import Field
from . import templates

class Register(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'regs.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, config: dict):
        super().__init__()

        # Save and/or process important variables
        self.__process_variables(obj)

        # Create logger object
        self.create_logger("{}.{}".format(self.owning_addrmap, self.path), config)
        self.logger.debug('Starting to process register "{}"'.format(obj.inst_name))

        # Create RTL for fields
        # Fields should be in order in RTL,therefore, use list
        for field in obj.fields():
            field_obj = Field(field, self.array_dimensions, config)

            if not config['disable_sanity']:
                field_obj.sanity_checks()

            self.children.append(field_obj)

        # Create generate block for register and add comment
        self.rtl_header.append("generate")
        for i in range(self.dimensions):
            self.rtl_header.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = chr(97+i),
                    limit = self.array_dimensions[i]))


        # End loops
        for i in range(self.dimensions-1, -1, -1):
            self.rtl_footer.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = chr(97+i)))

        # Assign variables from bus
        self.obj.current_idx = [0]

        if self.dimensions:
            rw_wire_assign_field = 'rw_wire_assign_multi_dim'
        else:
            rw_wire_assign_field = 'rw_wire_assign_1_dim'

        self.rtl_header.append(
            Register.templ_dict[rw_wire_assign_field]['rtl'].format(
                path = self.path,
                addr = self.obj.absolute_address,
                genvars = self.genvars_str,
                genvars_sum =self.genvars_sum_str,
                stride = self.obj.array_stride,
                depth = self.depth))

        self.yaml_signals_to_list(Register.templ_dict[rw_wire_assign_field])

        # Add wire/register instantiations
        self.rtl_header = [
            *[
                Register.templ_dict['signal_declaration'].format(
                    name = key,
                    type = value[0],
                    unpacked_dim = '[{}]'.format(
                        ']['.join(
                            [str(y) for y in value[1]]))
                        if value[1] else '')
                for (key, value) in self.get_signals().items()],
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


    def __process_variables(self, obj: node.RootNode):
        # Save object
        self.obj = obj

        # Save name
        self.name = obj.inst_name

        # Create full name
        self.owning_addrmap = obj.owning_addrmap.inst_name
        self.path = obj.get_path()\
                        .replace('[]', '')\
                        .replace('{}.'.format(self.owning_addrmap), '')

        self.path_underscored = self.path.replace('.', '_')

        # Determine dimensions of register
        if obj.is_array:
            self.sel_arr = 'array'
            self.array_dimensions = self.obj.array_dimensions
        else:
            self.sel_arr = 'single'
            self.array_dimensions = []

        self.depth = '[{}]'.format(']['.join(f"{i}" for i in self.array_dimensions))
        self.dimensions = len(self.array_dimensions)

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(self.dimensions)]
        self.genvars_str = ''.join(genvars)

        # Determine value to compare address with
        genvars_sum = []
        for i in range(self.dimensions):
            if i != 0:
                genvars_sum.append("+")
                genvars_sum.append("*".join(map(str,self.array_dimensions[self.dimensions-i:])))
                genvars_sum.append("*")

            genvars_sum.append(chr(97+self.dimensions-1-i))

        self.genvars_sum_str = ''.join(genvars_sum)

