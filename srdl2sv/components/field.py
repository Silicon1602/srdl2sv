import math
import importlib.resources as pkg_resources
import yaml

from systemrdl.node import FieldNode, SignalNode
from systemrdl.component import Reg, Regfile, Addrmap, Root
from systemrdl.rdltypes import PrecedenceType, AccessType, OnReadType, OnWriteType

# Local modules
from components.component import Component, TypeDef
from . import templates

class Field(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'fields.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: FieldNode,
            array_dimensions: list,
            config:dict,
            glbl_settings: dict):
        super().__init__(obj, config)

        # Save and/or process important variables
        self.__process_variables(obj, array_dimensions, glbl_settings)

        # Determine field types
        self.__process_fieldtype()

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
        self.__prepend_signal_declarations()

    def __add_combo(self):
        operations = []
        if self.obj.get_property('anded'):
            operations.append(['&', 'assign_anded_operation'])
        if self.obj.get_property('ored'):
            operations.append(['|', 'assign_ored_operation'])
        if self.obj.get_property('xored'):
            operations.append(['^', 'assign_xored_operation'])

        if len(operations) > 0:
            self.rtl_header.append(
                Field.templ_dict['combo_operation_comment']['rtl'].format(
                    path = self.path_underscored))

        self.rtl_header = [
            *self.rtl_header,
            *[Field.templ_dict[i[1]]['rtl'].format(
                path = self.path_underscored,
                genvars = self.genvars_str,
                op_verilog = i[0]) for i in operations]
            ]

        [self.yaml_signals_to_list(Field.templ_dict[i[1]]) for i in operations]


    def __process_fieldtype(self):
        try:
            if not self.config['enums']:
                raise AttributeError

            enum = self.obj.get_property('encode')

            # Rules for scope:
            #   - Regfiles or addrmaps have packages
            #   - An enum that is not defined within a register will go into the package
            #     of the first addrmap or regfile that is found when iterating through
            #     the parents
            #   - Regfiles don't need to be unique in a design. Therefore, the packages of
            #     regfiles shall be prepended by the addrmap name.
            #   - When the enum is defined in a register, that register will be prepended
            #     to the name of that enum.
            #
            # This procedure is expensive, but None.parent() will not work and therefore
            # kill the try block in most cases
            parent_scope = enum.get_parent_scope()

            self.logger.debug("Starting to parse '{}'".format(enum))

            if isinstance(parent_scope, Reg):
                enum_name = '__'.join([enum.get_scope_path().split('::')[-1], enum.__name__])
                parent_scope = parent_scope.parent_scope
            else:
                enum_name = enum.__name__

            path = []

            # Open up all parent scopes and append it to scope list
            while 1:
                if isinstance(parent_scope, Regfile):
                    path.append(parent_scope._scope_name)

                    # That's a lot of parent_scope's...
                    parent_scope = parent_scope.parent_scope
                else:
                    path.append(self.owning_addrmap)

                    break

            # Create string. Reverse list so that order starts at addrmap
            scope = '__'.join(reversed(path))

            # Create internal NamedTuple with information on Enum
            self.typedefs[enum_name] = TypeDef (
                scope=scope,
                width=self.obj.width,
                members= [(x.name, x.value) for x in self.obj.get_property('encode')]
            )

            # Save name of object
            self.field_type =\
                '::'.join(['_'.join([scope, 'pkg']), enum_name])

            self.logger.info("Parsed enum '{}'".format(enum_name))

        except AttributeError:
            # In case of an AttributeError, the encode property is None. Hence,
            # the field has a simple width
            if self.obj.width > 1:
                self.field_type = 'logic [{}:0]'.format(self.obj.width-1)
            else:
                self.field_type = 'logic'

    def __process_variables(self, obj: FieldNode, array_dimensions: list, glbl_settings: dict):
        # Create full name
        self.path_wo_field = '.'.join(self.path.split('.', -1)[0:-1])

        # Save dimensions of unpacked dimension
        self.array_dimensions = array_dimensions
        self.total_array_dimensions = array_dimensions

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(len(array_dimensions))]
        self.genvars_str = ''.join(genvars)

        # Write enable
        self.we_or_wel = self.obj.get_property('we') or self.obj.get_property('wel')

        # Save byte boundaries
        self.lsbyte = math.floor(obj.inst.lsb / 8)
        self.msbyte = math.floor(obj.inst.msb / 8)

        # Determine resets. This includes checking for async/sync resets,
        # the reset value, and whether the field actually has a reset
        self.rst = dict()

        reset_signal = obj.get_property("resetsignal")

        if reset_signal:
            self.rst = Field.process_reset_signal(reset_signal)
        else:
            # Only use global reset (if present) if no local reset is set
            self.rst = glbl_settings['field_reset']

        self.resets.add(self.rst['name'])

        # Value of reset must always be determined on field level
        self.rst['value'] = \
            '\'x' if not obj.get_property("reset") else\
                     obj.get_property('reset')

        # Define hardware access
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
            Field.templ_dict['field_comment']['rtl'].format(
                name = self.name,
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
            Field.templ_dict[sense_list]['rtl'].format(
                clk_name = "clk",
                rst_edge = self.rst['edge'],
                rst_name = self.rst['name']))

        # Add actual reset line
        if self.rst['name']:
            self.rtl_header.append(
                Field.templ_dict['rst_field_assign']['rtl'].format(
                    path = self.path_underscored,
                    rst_name = self.rst['name'],
                    rst_negl =  "!" if self.rst['active'] == "active_low" else "",
                    rst_value = self.rst['value'],
                    genvars = self.genvars_str))

            self.yaml_signals_to_list(Field.templ_dict['rst_field_assign'])

        self.rtl_header.append("begin")

        # Add name of actual field to Signal field
        # TODO

    def __prepend_signal_declarations(self):
        pass


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
                    Field.templ_dict['hw_access_we_wel']['rtl'].format(
                        negl = '!' if self.obj.get_property('wel') else '',
                        path = self.path_underscored,
                        genvars = self.genvars_str))
            else:
                access_rtl['hw_write'].append(
                    Field.templ_dict['hw_access_no_we_wel']['rtl'])

            access_rtl['hw_write'].append(
                Field.templ_dict['hw_access_field']['rtl'].format(
                    path = self.path_underscored,
                    genvars = self.genvars_str))

            self.yaml_signals_to_list(Field.templ_dict['hw_access_field'])

        # Define software access (if applicable)
        access_rtl['sw_write'] = []

        if self.sw_access in (AccessType.rw, AccessType.w):
            swwe = self.obj.get_property('swwe')
            swwel = self.obj.get_property('swwel')

            if isinstance(swwe, (FieldNode, SignalNode)):
                access_rtl['sw_write'].append(
                    Field.templ_dict['sw_access_field_swwe']['rtl'].format(
                        path_wo_field = self.path_wo_field,
                        genvars = self.genvars_str,
                        swwe = Component.get_signal_name(swwe)))
            elif isinstance(swwel, (FieldNode, SignalNode)):
                access_rtl['sw_write'].append(
                    Field.templ_dict['sw_access_field_swwel']['rtl'].format(
                        path_wo_field = self.path_wo_field,
                        genvars = self.genvars_str,
                        swwel = Component.get_signal_name(swwel)))
            else:
                access_rtl['sw_write'].append(
                    Field.templ_dict['sw_access_field']['rtl'].format(
                        path_wo_field = self.path_wo_field,
                        genvars = self.genvars_str))

            # Check if an onwrite property is set
            onwrite = self.obj.get_property('onwrite')

            if onwrite:
                if onwrite == OnWriteType.wuser:
                    self.logger.warning("The OnReadType.wuser is not yet supported!")
                elif onwrite in (OnWriteType.wclr, OnWriteType.wset):
                    access_rtl['sw_write'].append(
                        Field.templ_dict[str(onwrite)]['rtl'].format(
                            path = self.path_underscored,
                            genvars = self.genvars_str,
                            path_wo_field = self.path_wo_field
                            )
                        )
                else:
                    # If field spans multiple bytes, every byte shall have a seperate enable!
                    for j, i in enumerate(range(self.lsbyte, self.msbyte+1)):
                        access_rtl['sw_write'].append(
                            Field.templ_dict[str(onwrite)]['rtl'].format(
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
                        Field.templ_dict['sw_access_byte']['rtl'].format(
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
                    Field.templ_dict[str(onread)]['rtl'].format(
                        path = self.path_underscored,
                        genvars = self.genvars_str,
                        path_wo_field = self.path_wo_field
                        )
                    )

        # Add singlepulse property
        if self.obj.get_property('singlepulse'):
            access_rtl['singlepulse'] = [
                Field.templ_dict['singlepulse']['rtl'].format(
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
            Field.templ_dict['end_field_ff']['rtl'].format(
                path = self.path_underscored))


    def __add_ports(self):
        if self.hw_access in (AccessType.rw, AccessType.r):
            # Connect flops to output port
            self.rtl_header.append(
                Field.templ_dict['out_port_assign']['rtl'].format(
                    genvars = self.genvars_str,
                    path = self.path_underscored))

            self.yaml_signals_to_list(Field.templ_dict['out_port_assign'])

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


            # TODO: Counter & hw=r shouldn't work
