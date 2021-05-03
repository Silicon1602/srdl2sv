import math
import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode
from systemrdl.rdltypes import PrecedenceType, AccessType
from itertools import chain

TAB = "    "

class Field:
    # Save YAML template as class variable
    with open('srdl2sv/components/templates/fields.yaml', 'r') as file:
        templ_dict = yaml.load(file, Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, indent_lvl: int, dimensions: int):
        self.obj = obj
        self.rtl = []
        self.bytes = math.ceil(obj.width / 8)

        # Make a list of I/O that shall be added to the addrmap
        self.input_ports = []
        self.output_ports = []

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

        # Not all access types are required and the order might differ
        # depending on what types are defined and what precedence is
        # set. Therefore, first add all RTL into a dictionary and
        # later place it in the right order.
        #
        # The following RTL blocks are defined:
        #   - hw_write --> write access for the hardware interface
        #   - sw_write --> write access for the software interface
        #
        access_rtl = dict([])

        # Define hardware access (if applicable)
        access_rtl['hw_write'] = []

        if hw_access in (AccessType.rw, AccessType.w):
            if obj.get_property('we') or obj.get_property('wel'):
                access_rtl['hw_write'].append(
                    Field.templ_dict['hw_access_we_wel'].format(
                        negl = '!' if obj.get_property('wel') else '',
                        reg_name = obj.parent.inst_name,
                        field_name = obj.inst_name,
                        genvars = genvars_str,
                        indent = self.indent(indent_lvl)))

            access_rtl['hw_write'].append(
                Field.templ_dict['hw_access_field'].format(
                    reg_name = obj.parent.inst_name,
                    field_name = obj.inst_name,
                    genvars = genvars_str,
                    indent = self.indent(indent_lvl)))

        # Define software access (if applicable)
        access_rtl['sw_write'] = []

        if sw_access in (AccessType.rw, AccessType.w):
            access_rtl['sw_write'].append(
                Field.templ_dict['sw_access_field'].format(
                    reg_name = obj.parent.inst_name,
                    field_name = obj.inst_name,
                    genvars = genvars_str,
                    indent = self.indent(indent_lvl)))

            indent_lvl += 1

            # If field spans multiple bytes, every byte shall have a seperate enable!
            for i in range(self.bytes):
                access_rtl['sw_write'].append(
                    Field.templ_dict['sw_access_byte'].format(
                        reg_name = obj.parent.inst_name,
                        field_name = obj.inst_name,
                        genvars = genvars_str,
                        i = i,
                        indent = self.indent(indent_lvl)))

            indent_lvl -= 1

            access_rtl['sw_write'].append("{}end".format(self.indent(indent_lvl)))

        # Define else with correct indentation and add to dictionary
        access_rtl['else'] = ["{}else".format(self.indent(indent_lvl))]

        # Add empty string
        access_rtl[''] = ['']

        # Check if hardware has precedence (default `precedence = sw`)
        if precedence == 'PrecedenceType.sw':
            rtl_order = ['sw_write',
                         'else' if len(access_rtl['hw_write']) > 0 else '',
                         'hw_write']
        else:
            rtl_order = ['hw_write',
                         'else' if len(access_rtl['sw_write']) > 0 else '',
                         'sw_write']

        # Add dictionary to main RTL list in correct order
        self.rtl = [
            *self.rtl,
            *chain.from_iterable([access_rtl[i] for i in rtl_order])]

        indent_lvl -= 1

        self.rtl.append(
            Field.templ_dict['end_field_ff'].format(
                reg_name = obj.parent.inst_name,
                field_name = obj.inst_name,
                indent = self.indent(indent_lvl)))

        #####################
        # Add combo logic
        #####################
        operations = []
        if obj.get_property('anded'):
            operations.append(['anded', '&'])
        if obj.get_property('ored'):
            operations.append(['ored', '|'])
        if obj.get_property('xored'):
            operations.append(['xored', '^'])

        if len(operations) > 0:
            self.rtl.append(
                Field.templ_dict['combo_operation_comment'].format(
                    reg_name = obj.parent.inst_name,
                    field_name = obj.inst_name,
                    indent = self.indent(indent_lvl)))

        self.rtl = [
            *self.rtl,
            *[Field.templ_dict['assign_combo_operation'].format(
                field_name = obj.inst_name,
                reg_name = obj.parent.inst_name,
                genvars = genvars_str,
                op_name = i[0],
                op_verilog = i[1],
                indent = self.indent(indent_lvl)) for i in operations]]

        # TODO: Set sanity checks. For example, having no we but precedence = hw
        #       will cause weird behavior.


    @staticmethod
    def indent(level):
        return TAB*level

    def get_rtl(self) -> str:
        return '\n'.join(self.rtl)
