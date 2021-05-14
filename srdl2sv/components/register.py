import importlib.resources as pkg_resources
import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

# Local modules
from log.log import create_logger
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

        if obj.is_array:
            sel_arr = 'array'
            array_dimensions = obj.array_dimensions
        else:
            sel_arr = 'single'
            array_dimensions = [1]

        depth = '[{}]'.format(']['.join(f"{i}" for i in array_dimensions))
        dimensions = len(array_dimensions)

        # Create comment and provide user information about register he/she
        # is looking at.
        self.rtl_header.append(
            Register.templ_dict['reg_comment'].format(
                name = obj.inst_name,
                dimensions = dimensions,
                depth = depth))

        # Create wires every register
        self.rtl_header.append(
            Register.templ_dict['rw_wire_declare'].format(
                name = obj.inst_name,
                depth = depth))

        # Create generate block for register and add comment
        self.rtl_header.append("generate")
        for i in range(dimensions):
            self.rtl_header.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = chr(97+i),
                    limit = array_dimensions[i]))

        # Create RTL for fields
        # Fields should be in order in RTL,therefore, use list
        for field in obj.fields():
            field_obj = Field(field, dimensions, config)

            if not config['disable_sanity']:
                field_obj.sanity_checks()

            self.children.append(field_obj)

        # End loops
        for i in range(dimensions-1, -1, -1):
            self.rtl_footer.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = chr(97+i)))

    def __process_variables(self, obj: node.RootNode):
        # Save object
        self.obj = obj

        # Create full name
        self.owning_addrmap = obj.owning_addrmap.inst_name
        self.path = obj.get_path()\
                        .replace('[]', '')\
                        .replace('{}.'.format(self.owning_addrmap), '')

        self.path_underscored = self.path.replace('.', '_')

        self.name = obj.inst_name
