import math
import importlib.resources as pkg_resources
import yaml

from systemrdl import RDLCompiler, RDLCompileError, RDLWalker, RDLListener, node
from systemrdl.node import FieldNode
from systemrdl.rdltypes import PrecedenceType, AccessType, OnReadType, OnWriteType

# Local modules
from components.component import Component, Port
from . import templates

class Field(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'fields.yaml'),
        Loader=yaml.FullLoader)

    def __init__(self, obj: node.RootNode, dimensions: list, config:dict):
        super().__init__()

        # Save and/or process important variables
        self.__process_variables(obj, dimensions)

        # Create logger object
        self.create_logger("{}.{}".format(self.owning_addrmap, self.path), config)
        self.logger.debug('Starting to process field "{}"'.format(obj.inst_name))

        ##################################################################################
        # LIMITATION:
        # v1.x of the systemrdl-compiler does not support non-homogeneous arrays.
        # It is planned, however, for v2.0.0 of the compiler. More information
        # can be found here: https://github.com/SystemRDL/systemrdl-compiler/issues/51
        ##################################################################################
        # Print a summary
        self.rtl_header.append(self.summary())

        # Generate RTL
        self.__add_always_ff()
        self.__add_access_rtl()
        self.__add_combo()
        self.__add_ports()

    def __add_combo(self):
        operations = []
        if self.obj.get_property('anded'):
            operations.append(['anded', '&'])
        if self.obj.get_property('ored'):
            operations.append(['ored', '|'])
        if self.obj.get_property('xored'):
            operations.append(['xored', '^'])

        if len(operations) > 0:
            self.rtl_header.append(
                Field.templ_dict['combo_operation_comment'].format(
                    path = self.path_underscored))

        self.rtl_header = [
            *self.rtl_header,
            *[Field.templ_dict['assign_combo_operation'].format(
                path = self.path_underscored,
                genvars = self.genvars_str,
                op_name = i[0],
                op_verilog = i[1]) for i in operations]
            ]


    def __process_variables(self, obj: node.RootNode, dimensions: list):
        # Save object
        self.obj = obj

        # Create full name
        self.owning_addrmap = obj.owning_addrmap.inst_name
        self.path = obj.get_path()\
                        .replace('[]', '')\
                        .replace('{}.'.format(self.owning_addrmap), '')

        self.path_underscored = self.path.replace('.', '_')
        self.path_wo_field = '.'.join(self.path.split('.', -1)[0:-1])

        # Save dimensions of unpacked dimension
        self.dimensions = dimensions

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(len(dimensions))]
        self.genvars_str = ''.join(genvars)

        # Write enable
        self.we_or_wel = self.obj.get_property('we') or self.obj.get_property('wel')

        # Save byte boundaries
        self.lsbyte = math.floor(obj.inst.lsb / 8)
        self.msbyte = math.floor(obj.inst.msb / 8)

        # Determine resets. This includes checking for async/sync resets,
        # the reset value, and whether the field actually has a reset
        self.rst = dict()

        try:
            rst_signal = obj.get_property("resetsignal")

            self.rst['name']  = rst_signal.inst_name
            self.rst['async'] = rst_signal.get_property("async")
            self.rst['type'] = "asynchronous" if self.rst['async'] else "synchronous"

            # Active low or active high?
            if rst_signal.get_property("activelow"):
                self.rst['edge'] = "negedge"
                self.rst['active'] = "active_low"
            else:
                self.rst['edge'] = "posedge"
                self.rst['active'] = "active_high"

            # Value of reset?
            self.rst['value'] = '\'x' if obj.get_property("reset") == None else\
                                obj.get_property('reset')
        except:
            self.rst['async'] = False
            self.rst['name'] = None
            self.rst['edge'] = None
            self.rst['value'] = "'x"
            self.rst['active'] = "-"
            self.rst['type'] = "-"

        self.hw_access = obj.get_property('hw')
        self.sw_access = obj.get_property('sw')
        self.precedence = obj.get_property('precedence')


    def summary(self):
        # Additional flags that are set
        misc_flags = set(self.obj.list_properties())

        # Remove some flags that are not interesting
        # or that are listed elsewhere
        misc_flags.discard('hw')
        misc_flags.discard('reset')

        # Add comment with summary on field's properties
        return \
            Field.templ_dict['field_comment'].format(
                name = self.obj.inst_name,
                hw_access = str(self.hw_access)[11:],
                sw_access = str(self.sw_access)[11:],
                hw_precedence = '(precedence)' if self.precedence == PrecedenceType.hw else '',
                sw_precedence = '(precedence)' if self.precedence == PrecedenceType.sw else '',
                rst_active = self.rst['active'],
                rst_type = self.rst['type'],
                misc_flags = misc_flags if misc_flags else '-',
                lsb = self.obj.lsb,
                msb = self.obj.msb,
                path_wo_field = self.path_wo_field)

    def __add_always_ff(self):
        # Handle always_ff
        sense_list = 'sense_list_rst' if self.rst['async'] else 'sense_list_no_rst'

        self.rtl_header.append(
            Field.templ_dict[sense_list].format(
                clk_name = "clk",
                rst_edge = self.rst['edge'],
                rst_name = self.rst['name']))

        # Add actual reset line
        if self.rst['name']:
            self.rtl_header.append(
                Field.templ_dict['rst_field_assign'].format(
                    path = self.path_underscored,
                    rst_name = self.rst['name'],
                    rst_negl =  "!" if self.rst['active'] == "active_high" else "",
                    rst_value = self.rst['value'],
                    genvars = self.genvars_str))

        self.rtl_header.append("begin")

    def __add_access_rtl(self):
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

        if self.hw_access in (AccessType.rw, AccessType.w):
            if self.we_or_wel:
                access_rtl['hw_write'].append(
                    Field.templ_dict['hw_access_we_wel'].format(
                        negl = '!' if self.obj.get_property('wel') else '',
                        path = self.path_underscored,
                        genvars = self.genvars_str))
            else:
                access_rtl['hw_write'].append(
                    Field.templ_dict['hw_access_no_we_wel'])

            access_rtl['hw_write'].append(
                Field.templ_dict['hw_access_field'].format(
                    path = self.path_underscored,
                    genvars = self.genvars_str))

        # Define software access (if applicable)
        access_rtl['sw_write'] = []

        if self.sw_access in (AccessType.rw, AccessType.w):
            access_rtl['sw_write'].append(
                Field.templ_dict['sw_access_field'].format(
                    path_wo_field = self.path_wo_field,
                    genvars = self.genvars_str))

            # Check if an onwrite property is set
            onwrite = self.obj.get_property('onwrite')

            if onwrite:
                if onwrite == OnWriteType.wuser:
                    self.logger.warning("The OnReadType.wuser is not yet supported!")
                elif onwrite in (OnWriteType.wclr, OnWriteType.wset):
                    access_rtl['sw_write'].append(
                        Field.templ_dict[str(onwrite)].format(
                            path = self.path_underscored,
                            genvars = self.genvars_str,
                            path_wo_field = self.path_wo_field
                            )
                        )
                else:
                    # If field spans multiple bytes, every byte shall have a seperate enable!
                    for j, i in enumerate(range(self.lsbyte, self.msbyte+1)):
                        access_rtl['sw_write'].append(
                            Field.templ_dict[str(onwrite)].format(
                                path = self.path_underscored,
                                genvars = self.genvars_str,
                                i = i,
                                msb_bus = str(8*(i+1)-1 if i != self.msbyte else self.obj.msb),
                                bus_w = str(8 if i != self.msbyte else self.obj.width-(8*j)),
                                msb_field = str(8*(j+1)-1 if i != self.msbyte else self.obj.width-1),
                                field_w = str(8 if i != self.msbyte else self.obj.width-(8*j))))
            else:
                # Normal write
                # If field spans multiple bytes, every byte shall have a seperate enable!
                for j, i in enumerate(range(self.lsbyte, self.msbyte+1)):
                    access_rtl['sw_write'].append(
                        Field.templ_dict['sw_access_byte'].format(
                            path = self.path_underscored,
                            genvars = self.genvars_str,
                            i = i,
                            msb_bus = str(8*(i+1)-1 if i != self.msbyte else self.obj.msb),
                            bus_w = str(8 if i != self.msbyte else self.obj.width-(8*j)),
                            msb_field = str(8*(j+1)-1 if i != self.msbyte else self.obj.width-1),
                            field_w = str(8 if i != self.msbyte else self.obj.width-(8*j))))

            access_rtl['sw_write'].append("end")

        onread = self.obj.get_property('onread')

        access_rtl['sw_read'] = []
        if self.sw_access in (AccessType.rw, AccessType.r) and onread:
            if onread == OnReadType.ruser:
                self.logger.warning("The OnReadType.ruser is not yet supported!")
            else:
                access_rtl['sw_read'].append(
                    Field.templ_dict[str(onread)].format(
                        path = self.path_underscored,
                        genvars = self.genvars_str,
                        path_wo_field = self.path_wo_field
                        )
                    )

        # Add singlepulse property
        if self.obj.get_property('singlepulse'):
            access_rtl['singlepulse'] = [
                Field.templ_dict['singlepulse'].format(
                    path = self.path_underscored,
                    genvars = self.genvars_str)
                ]
        else:
            access_rtl['singlepulse'] = []

        # Define else
        access_rtl['else'] = ["else"]

        # Add empty string
        access_rtl[''] = ['']

        # Check if hardware has precedence (default `precedence = sw`)
        if self.precedence == PrecedenceType.sw:
            order_list = [
                'sw_write',
                'sw_read',
                'hw_write',
                'singlepulse'
                ]
        else:
            order_list = [
                'hw_write',
                'sw_write',
                'sw_read',
                'singlepulse'
                ]

        # Add appropriate else
        order_list_rtl = []

        for i in order_list:
            # Still a loop and not a list comprehension since this might
            # get longer in the future and thus become unreadable
            if len(access_rtl[i]) > 0:
                order_list_rtl = [*order_list_rtl, *access_rtl[i]]
                order_list_rtl.append("else")

        # Remove last pop
        order_list_rtl.pop()

        # Chain access RTL to the rest of the RTL
        self.rtl_header = [*self.rtl_header, *order_list_rtl]

        self.rtl_header.append(
            Field.templ_dict['end_field_ff'].format(
                path = self.path_underscored))


    def __add_ports(self):
        # Port is writable by hardware --> Input port from hardware
        if self.hw_access in (AccessType.rw, AccessType.w):
            self.ports['input'].append(
                Port("{}_in".format(self.path_underscored),
                     "",
                     self.dimensions
                ))

            # Port has enable signal --> create such an enable
            if self.we_or_wel:
                self.ports['input'].append(
                    Port("{}_hw_wr".format(self.path_underscored),
                         "",
                         self.dimensions
                    ))

        if self.hw_access in (AccessType.rw, AccessType.r):
            self.ports['output'].append(
                Port("{}_r".format(self.path_underscored),
                     "[{}:0]".format(self.obj.width-1) if self.obj.width > 1 else "",
                     self.dimensions
                ))

            # Connect flops to output port
            self.rtl_header.append(
                Field.templ_dict['out_port_assign'].format(
                    genvars = self.genvars_str,
                    path = self.path_underscored))


    def sanity_checks(self):
        # If hw=rw/sw=[r]w and hw has no we/wel, sw will never be able to write
        if not self.we_or_wel and\
                self.precedence == PrecedenceType.hw and \
                self.hw_access in (AccessType.rw, AccessType.w) and \
                self.sw_access in (AccessType.rw, AccessType.w):

            self.logger.warning("Fields with hw=rw/sw=[r]w, we/wel not set and "\
                                "precedence for hardware will render software's "\
                                "write property useless since hardware will "\
                                "write every cycle.")
