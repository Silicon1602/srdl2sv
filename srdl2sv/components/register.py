import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode

from components.field import Field

TAB = "    "

class Register:
    # Save YAML template as class variable
    with open('srdl2sv/components/templates/regs.yaml', 'r') as file:
        templ_dict = yaml.load(file, Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode):
        self.obj = obj
        self.name = obj.inst_name
        self.rtl = []

        if obj.is_array:
            sel_arr = 'array'
            array_dimensions = obj.array_dimensions
        else:
            sel_arr = 'single'
            array_dimensions = [1]

        depth = '[{}]'.format(']['.join(f"{i}" for i in array_dimensions))
        dimensions = len(array_dimensions)
        indent_lvl = 0

        # Create comment and provide user information about register he/she
        # is looking at.
        self.rtl.append(
            Register.templ_dict['reg_comment'].format(
                name = obj.inst_name,
                dimensions = dimensions,
                depth = depth))

        # Create wires every register
        self.rtl.append(
            Register.templ_dict['rw_wire_declare'].format(
                name = obj.inst_name,
                depth = depth))

        # Create generate block for register and add comment
        self.rtl.append("generate")
        for i in range(dimensions):
            self.rtl.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = chr(97+i),
                    limit = array_dimensions[i],
                    indent = self.indent(i)))

            indent_lvl = i

        indent_lvl += 1

        # Create RTL for fields
        # Fields should be in order in RTL,therefore, use list
        self.fields = []

        for field in obj.fields():
            field_obj = Field(field, indent_lvl, dimensions)
            self.fields.append(field_obj)

            self.rtl += field_obj.rtl

        # End loops
        for i in range(dimensions-1, -1, -1):
            self.rtl.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = chr(97+i),
                    indent = self.indent(i)))


    @staticmethod
    def indent(level):
        return TAB*level

    def get_rtl(self) -> str:
        return '\n'.join(self.rtl)
