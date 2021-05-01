import yaml
import math

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode
from systemrdl.rdltypes import PrecedenceType, AccessType


TAB = "    "

class Field:
    # Save YAML template as class variable
    with open('srdl2sv/components/templates/fields.yaml', 'r') as file:
        templ_dict = yaml.load(file, Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, indent_lvl: int, dimensions: int):
        self.obj = obj
        self.rtl = []
        self.bytes = math.ceil(obj.width / 8)

        ##################################################################################
        # LIMITATION:
        # v1.x of the systemrdl-compiler does not support non-homogeneous arrays.
        # It is planned, however, for v2.0.0 of the compiler. More information
        # can be found here: https://github.com/SystemRDL/systemrdl-compiler/issues/51
        ##################################################################################

        # Determine resets. This includes checking for async/sync resets,
        # the reset value, and whether the field actually has a reset
        try:
            rst_signal = obj.get_property("resetsignal")
            rst_name  = rst_signal.inst_name
            rst_async = rst_signal.get_property("async")
            rst_type = "asynchronous" if rst_async else "synchronous"

            # Active low or active high?
            if rst_signal.get_property("activelow"):
                rst_edge = "negedge"
                rst_negl = "!"
                rst_active = "active_low"
            else:
                rst_edge = "posedge"
                rst_negl = ""
                rst_active = "active_high"

            print(obj.get_property('reset'))
            # Value of reset?
            rst_value = '\'x' if obj.get_property("reset") == None else obj.get_property('reset')
        except:
            rst_async = False
            rst_name = None
            rst_negl = None
            rst_edge = None
            rst_value = "'x"
            rst_active = "-"
            rst_type = "-"

        # Get certain properties
        hw_access = obj.get_property('hw')
        sw_access = obj.get_property('sw')
        precedence = obj.get_property('precedence')

        # Add comment with summary on field's properties
        self.rtl.append(
            Field.templ_dict['field_comment'].format(
                name = obj.inst_name,
                hw_access = str(hw_access)[11:],
                sw_access = str(sw_access)[11:],
                hw_precedence = '(precedence)' if precedence == PrecedenceType.hw else '',
                sw_precedence = '(precedence)' if precedence == PrecedenceType.sw else '',
                rst_active = rst_active,
                rst_type = rst_type,
                indent = self.indent(indent_lvl)))

        # Handle always_ff
        sense_list = 'sense_list_rst' if rst_async else 'sense_list_no_rst'

        self.rtl.append(
            Field.templ_dict[sense_list].format(
                clk_name = "clk",
                rst_edge = rst_edge,
                rst_name = rst_name,
                indent = self.indent(indent_lvl)))


        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(dimensions)]
        genvars_str = ''.join(genvars)

        # Add actual reset line
        if rst_name:
            indent_lvl += 1

            self.rtl.append(
                Field.templ_dict['rst_field_assign'].format(
                    field_name = obj.inst_name,
                    rst_name = rst_name,
                    rst_negl = rst_negl,
                    rst_value = rst_value,
                    genvars = genvars_str,
                    indent = self.indent(indent_lvl)))

        self.rtl.append("{}begin".format(self.indent(indent_lvl)))

        indent_lvl += 1

        # Define hardware access (if applicable)
        hw_access_rtl = []

        if hw_access == AccessType.rw or hw_access == AccessType.w:
            if obj.get_property('we') or obj.get_property('wel'):
                hw_access_rtl.append(
                    Field.templ_dict['hw_access_we_wel'].format(
                        negl = '!' if obj.get_property('wel') else '',
                        reg_name = obj.parent.inst_name,
                        field_name = obj.inst_name,
                        genvars = genvars_str,
                        indent = self.indent(indent_lvl)))

            hw_access_rtl.append(
                Field.templ_dict['hw_access_field'].format(
                    reg_name = obj.parent.inst_name,
                    field_name = obj.inst_name,
                    genvars = genvars_str,
                    indent = self.indent(indent_lvl)))

        # Define software access (if applicable)
        sw_access_rtl = []

        # TODO: if sw_access_enabled
        sw_access_rtl.append(
            Field.templ_dict['sw_access_field'].format(
                reg_name = obj.parent.inst_name,
                field_name = obj.inst_name,
                genvars = genvars_str,
                indent = self.indent(indent_lvl)))

        indent_lvl += 1

        # If field spans multiple bytes, every byte shall have a seperate enable!
        for i in range(self.bytes):
            sw_access_rtl.append(
                Field.templ_dict['sw_access_byte'].format(
                    reg_name = obj.parent.inst_name,
                    field_name = obj.inst_name,
                    genvars = genvars_str,
                    i = i,
                    indent = self.indent(indent_lvl)))

            sw_access_rtl.append("")

        indent_lvl -= 1

        sw_access_rtl.append("{}end".format(self.indent(indent_lvl)))

        # Check if hardware has precedence (default `precedence = sw`)
        if precedence == 'PrecedenceType.sw':
            self.rtl = [*self.rtl,
                        *sw_access_rtl,
                        '{}else'.format(self.indent(indent_lvl)),
                        *hw_access_rtl]
        else:
            self.rtl = [*self.rtl,
                        *sw_access_rtl,
                        '{}else'.format(self.indent(indent_lvl)),
                        *hw_access_rtl]

        indent_lvl -= 1

        self.rtl.append(
            Field.templ_dict['end_field_ff'].format(
                reg_name = obj.parent.inst_name,
                field_name = obj.inst_name,
                indent = self.indent(indent_lvl)))



    @staticmethod
    def indent(level):
        return TAB*level

    def get_rtl(self) -> str:
        return '\n'.join(self.rtl)
