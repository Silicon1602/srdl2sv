import math

import importlib.resources as pkg_resources
import sys
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

        # HW Access can be handled in __init__ function but SW access
        # must be handled in a seperate method that can be called
        # seperately in case of alias registers
        self.__add_always_ff()
        self.__add_hw_access()
        self.__add_combo()
        self.__add_swmod_swacc()
        self.__add_counter()

        self.add_sw_access(obj)

    def add_sw_access(self, obj, alias = False):
        access_rtl = dict()

        if alias:
            owning_addrmap, full_path, path, path_underscored =\
                Field.create_underscored_path_static(obj)
        else:
            owning_addrmap, full_path, path, path_underscored =\
                self.owning_addrmap, self.full_path, self.path, self.path_underscored

        path_wo_field = '__'.join(path.split('.', -1)[0:-1])

        # Define software access (if applicable)
        access_rtl['sw_write'] = ([], False)

        if obj.get_property('sw') in (AccessType.rw, AccessType.w):
            swwe = obj.get_property('swwe')
            swwel = obj.get_property('swwel')

            if isinstance(swwe, (FieldNode, SignalNode)):
                access_rtl['sw_write'][0].append(
                    self.process_yaml(
                        Field.templ_dict['sw_access_field_swwe'],
                        {'path_wo_field': path_wo_field,
                         'genvars': self.genvars_str,
                         'swwe': self.get_signal_name(swwe),
                         'field_type': self.field_type}
                    )
                )
            elif isinstance(swwel, (FieldNode, SignalNode)):
                access_rtl['sw_write'][0].append(
                    self.process_yaml(
                        Field.templ_dict['sw_access_field_swwel'],
                        {'path_wo_field': path_wo_field,
                         'genvars': self.genvars_str,
                         'swwel': self.get_signal_name(swwel),
                         'field_type': self.field_type}
                    )
                )
            else:
                access_rtl['sw_write'][0].append(
                    self.process_yaml(
                        Field.templ_dict['sw_access_field'],
                        {'path_wo_field': path_wo_field,
                         'genvars': self.genvars_str,
                         'field_type': self.field_type}
                    )
                )

            # Check if an onwrite property is set
            onwrite = obj.get_property('onwrite')

            if onwrite:
                if onwrite == OnWriteType.wuser:
                    self.logger.warning("The OnReadType.wuser is not yet supported!")
                elif onwrite in (OnWriteType.wclr, OnWriteType.wset):
                    access_rtl['sw_write'][0].append(
                        self.process_yaml(
                            Field.templ_dict[str(onwrite)],
                            {'path': path_underscored,
                             'genvars': self.genvars_str,
                             'width': obj.width,
                             'path_wo_field': path_wo_field,
                             'field_type': self.field_type}
                        )
                    )
                else:
                    # If field spans multiple bytes, every byte shall have a seperate enable!
                    for j, i in enumerate(range(self.lsbyte, self.msbyte+1)):
                        msb_bus = 8*(i+1)-1 if i != self.msbyte else obj.msb
                        lsb_bus = 8*i if i != self.lsbyte else obj.inst.lsb

                        access_rtl['sw_write'][0].append(
                            self.process_yaml(
                                Field.templ_dict[str(onwrite)],
                                {'path': path_underscored,
                                 'genvars': self.genvars_str,
                                 'i': i,
                                 'width': obj.width,
                                 'msb_bus': str(msb_bus),
                                 'lsb_bus': str(lsb_bus),
                                 'msb_field': str(msb_bus-obj.inst.lsb),
                                 'lsb_field': str(lsb_bus-obj.inst.lsb),
                                 'field_type': self.field_type}
                            )
                        )

            else:
                # Normal write
                # If field spans multiple bytes, every byte shall have a seperate enable!
                for j, i in enumerate(range(self.lsbyte, self.msbyte+1)):
                    msb_bus = 8*(i+1)-1 if i != self.msbyte else obj.msb
                    lsb_bus = 8*i if i != self.lsbyte else obj.inst.lsb

                    access_rtl['sw_write'][0].append(
                        self.process_yaml(
                            Field.templ_dict['sw_access_byte'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'i': i,
                             'msb_bus': str(msb_bus),
                             'lsb_bus': str(lsb_bus),
                             'msb_field': str(msb_bus-obj.inst.lsb),
                             'lsb_field': str(lsb_bus-obj.inst.lsb),
                             'field_type': self.field_type}
                        )
                    )

            access_rtl['sw_write'][0].append("end")

        onread = obj.get_property('onread')

        access_rtl['sw_read'] = ([], False)
        if obj.get_property('sw') in (AccessType.rw, AccessType.r):
            # Append to list of registers that can read
            self.readable_by.add(path_wo_field)

            # Set onread properties
            if onread == OnReadType.ruser:
                self.logger.error("The OnReadType.ruser is not yet supported!")
            elif onread:
                access_rtl['sw_read'][0].append(
                    self.process_yaml(
                        Field.templ_dict[str(onread)],
                        {'width': obj.width,
                         'path': path_underscored,
                         'genvars': self.genvars_str,
                         'path_wo_field': path_wo_field}
                        )
                    )

        # Add singlepulse property
        # Property cannot be overwritten by alias
        if obj.get_property('singlepulse'):
            self.access_rtl['singlepulse'] = ([
                self.process_yaml(
                    Field.templ_dict['singlepulse'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str}
                )
                ],
                True)
        else:
            self.access_rtl['singlepulse'] = ([], False)

        # Add to global dictionary
        try:
            # Alias, so add 'else'
            self.access_rtl['sw_read'] = \
                 [*self.access_rtl['sw_read'], access_rtl['sw_read']]
            self.access_rtl['sw_write'] = \
                 [*self.access_rtl['sw_write'], access_rtl['sw_write']]
        except KeyError:
            self.access_rtl['sw_read'] = [access_rtl['sw_read']]
            self.access_rtl['sw_write'] = [access_rtl['sw_write']]

    def __add_counter(self):
        if self.obj.get_property('counter'):
            self.logger.debug("Detected counter property")

            # Determine saturation values
            if isinstance(self.obj.get_property('incrsaturate'), bool):
                if self.obj.get_property('incrsaturate'):
                    incr_sat_value = 2**self.obj.width-1
                else:
                    incr_sat_value = False
            else:
                incr_sat_value = self.obj.get_property('incrsaturate')

            if isinstance(self.obj.get_property('decrsaturate'), bool):
                if self.obj.get_property('decrsaturate'):
                    decr_sat_value = 2**self.obj.width-1
                else:
                    decr_sat_value = False
            else:
                decr_sat_value = self.obj.get_property('decrsaturate')

            # Determine with what value the counter is incremented
            # According to the spec, the incrvalue/decrvalue default to '1'
            obj_incr_value = self.obj.get_property('incrvalue')
            obj_decr_value = self.obj.get_property('decrvalue')
            obj_incr_width = self.obj.get_property('incrwidth')
            obj_decr_width = self.obj.get_property('decrwidth')

            if obj_incr_value == 0:
                incr_value = None
                incr_width = 0
            elif obj_incr_value is None:
                if obj_incr_width:
                    # Decrement value is not set. Check if incrwidth is set and use
                    # that is applicable
                    incr_value = False
                    incr_width = obj_incr_width

                    # Doesn't return RTL, only adds input port
                    self.process_yaml(
                        Field.templ_dict['counter_incr_input'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width-1
                        }
                    )
                else:
                    # Otherwise, use default value according to LRM
                    incr_value = '1'
                    incr_width = 1
            elif isinstance(obj_incr_value, int):
                incr_value = str(obj_incr_value)
                incr_width = math.floor(math.log2(obj_incr_value)+1)

                if obj_incr_width:
                    self.logger.error(
                        "The 'incrwidth' and 'incrvalue' properties are both "\
                        "defined. This is not legal and the incrwidth property "\
                        "will be ignored!")
            else:
                incr_value = self.get_signal_name(obj_incr_value)
                incr_width = obj_incr_value.width

                if obj_incr_value.width > self.obj.width:
                    self.logger.error(
                        "Width of 'incr_value' signal '{}' is wider than current "\
                        "counter field. This could potentially cause ugly errors.".format(
                            obj_incr_value.get_path()))

                if obj_incr_width:
                    self.logger.error(
                        "The 'incrwidth' and 'incrvalue' properties are both "\
                        "defined. This is not legal and the incrwidth property "\
                        "will be ignored!")


            if incr_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_incr_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width-1,
                         'incr_value': incr_value,
                        }
                    )
                )

            if obj_decr_value == 0:
                decr_value = None
                decr_width = 0
            elif obj_decr_value is None:
                if obj_decr_width:
                    # Decrement value is not set. Check if decrwidth is set and use
                    # that is applicable
                    decr_value = False
                    decr_width = obj_decr_width

                    # Doesn't return RTL, only adds input port
                    self.process_yaml(
                        Field.templ_dict['counter_decr_input'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'decr_width': decr_width-1
                        }
                    )
                else:
                    # Otherwise, use default value according to LRM
                    decr_value = '1'
                    decr_width = 1
            elif isinstance(obj_decr_value, int):
                decr_value = str(obj_decr_value)
                decr_width = math.floor(math.log2(obj_decr_value)+1)

                if obj_decr_width:
                    self.logger.error(
                        "The 'decrwidth' and 'decrvalue' properties are both "\
                        "defined. This is not legal and the decrwidth property "\
                        "will be ignored!")
            else:
                decr_value = self.get_signal_name(obj_decr_value)
                decr_width = obj_decr_value.width

                if obj_decr_value.width > self.obj.width:
                    self.logger.error(
                        "Width of 'decr_value' signal '{}' is wider than current "\
                        "counter field. This could potentially cause ugly errors.".format(
                            obj_decr_value.get_path()))

                if obj_decr_width:
                    self.logger.error(
                        "The 'decrwidth' and 'decrvalue' properties are both "\
                        "defined. This is not legal and the decrwidth property "\
                        "will be ignored!")


            if decr_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_decr_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'decr_width': decr_width-1,
                         'decr_value': decr_value,
                        }
                    )
                )

            if (incr_width or incr_value) and (decr_width or decr_value):
                sat_condition = []
                if incr_sat_value:
                    sat_condition.append(
                        self.process_yaml(
                            Field.templ_dict['incr_decr_sat_counter_condition'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'greater_smaller': '>',
                             'sat_value': incr_sat_value
                            }
                        )
                    )

                if decr_sat_value:
                    if sat_condition:
                        sat_condition.append(' && ')

                    sat_condition.append(
                        self.process_yaml(
                            Field.templ_dict['incr_decr_sat_counter_condition'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'greater_smaller': '<',
                             'sat_value': decr_sat_value
                            }
                        )
                    )

                counter_logic = self.process_yaml(
                    Field.templ_dict['incr_decr_counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'incr_decr_sat_counter_condition': ''.join(sat_condition),
                    }
                )
            elif incr_width or incr_value:
                sat_condition = self.process_yaml(
                    Field.templ_dict['incr_sat_counter_condition'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'sat_value': incr_sat_value,
                    }
                ) if incr_sat_value else '1'

                counter_logic = self.process_yaml(
                    Field.templ_dict['incr_counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'incr_sat_counter_condition': sat_condition,
                    }
                )
            elif decr_width or decr_value:
                sat_condition = self.process_yaml(
                    Field.templ_dict['decr_sat_counter_condition'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'sat_value': decr_sat_value,
                    }
                ) if decr_sat_value else '1'

                counter_logic = self.process_yaml(
                    Field.templ_dict['decr_counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'decr_sat_counter_condition': sat_condition,
                    }
                )
            else:
                self.logger.fatal("Illegal counter configuration! Both 'incr_value' "\
                                  "and 'decr_value' are forced to 0. If you intended "\
                                  "to use 'incr_width' or 'decr_width', simply don't "\
                                  "force 'incr_value' or 'decr_value' to any value.")
                sys.exit(1)

            self.rtl_footer.append(
                self.process_yaml(
                    Field.templ_dict['counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'counter_logic': counter_logic,
                     'field_type': self.field_type,
                    }
                )
            )

    def __add_swmod_swacc(self):
        if self.obj.get_property('swmod'):
            self.logger.debug("Field has swmod property")

            swmod_assigns = list()

            # Check if read side-effects are defined. 
            if self.obj.get_property('onread'):
                swmod_assigns.append(
                    self.process_yaml(
                        Field.templ_dict['swmod_assign'],
                        {'path': self.path_underscored,
                         'path_wo_field': self.path_wo_field,
                         'genvars': self.genvars_str,
                         'rd_wr': 'rd',
                         'msbyte': self.msbyte,
                         'lsbyte': self.lsbyte,
                         'swmod_assigns': '\n'.join(swmod_assigns)
                        }
                    )
                )

            # Check if SW has write access to the field
            if self.obj.get_property('sw') in (AccessType.rw, AccessType.w):
                swmod_assigns.append(
                    self.process_yaml(
                        Field.templ_dict['swmod_assign'],
                        {'path': self.path_underscored,
                         'path_wo_field': self.path_wo_field,
                         'genvars': self.genvars_str,
                         'rd_wr': 'wr',
                         'msbyte': self.msbyte,
                         'lsbyte': self.lsbyte,
                         'swmod_assigns': '\n'.join(swmod_assigns)
                        }
                    )
                )

            swmod_props = self.process_yaml(
                Field.templ_dict['swmod_always_comb'],
                {'path': self.path_underscored,
                 'genvars': self.genvars_str,
                 'swmod_assigns': '\n'.join(swmod_assigns)
                }
            )

            if not swmod_assigns:
                self.logger.warning("Field has swmod property but the field is never "\
                                    "modified by software.")
        else:
            swmod_props = ''

        if self.obj.get_property('swacc') and \
                self.obj.get_property('sw') in (AccessType.rw, AccessType.r):

            self.logger.debug("Field has swacc property")

            swacc_props = self.process_yaml(
                Field.templ_dict['swacc_assign'],
                {'path': self.path_underscored,
                 'path_wo_field': self.path_wo_field,
                 'genvars': self.genvars_str,
                 'msbyte': self.msbyte,
                 'lsbyte': self.lsbyte,
                 }
            )
        elif self.obj.get_property('swacc'):
            self.logger.warning("Field has swacc property but the field is never "\
                                "accessed by software.")

            swacc_props = ''
        else:
            swacc_props = ''

        self.rtl_footer = [*self.rtl_footer, swmod_props, swacc_props]

    def __add_hw_access(self):
        # Define hardware access (if applicable)
        if self.obj.get_property('counter'):
            self.access_rtl['hw_write'] = ([
                self.process_yaml(
                    Field.templ_dict['hw_access_counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'field_type': self.field_type}
                )
            ],
            False)
        elif self.obj.get_property('hw') in (AccessType.rw, AccessType.w):
            write_condition = 'hw_access_we_wel' if self.we_or_wel else 'hw_access_no_we_wel'

            # if-line of hw-access
            self.access_rtl['hw_write'] = ([
                self.process_yaml(
                    Field.templ_dict[write_condition],
                    {'negl': '!' if self.obj.get_property('wel') else '',
                     'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'field_type': self.field_type}
                )
            ],
            write_condition == 'hw_access_no_we_wel') # Abort if no condition is set

            # Actual assignment of register
            self.access_rtl['hw_write'][0].append(
                self.process_yaml(
                    Field.templ_dict['hw_access_field'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'field_type': self.field_type}
                )
            )
        else:
            self.access_rtl['hw_write'] = ([], False)

        # Hookup flop to output port in case register is readable by hardware
        if self.obj.get_property('hw') in (AccessType.rw, AccessType.r):
            # Connect flops to output port
            self.rtl_footer.append(
                self.process_yaml(
                    Field.templ_dict['out_port_assign'],
                    {'genvars': self.genvars_str,
                     'path': self.path_underscored,
                     'field_type': self.field_type}
                )
            )

    def create_rtl(self):
        # Not all access types are required and the order might differ
        # depending on what types are defined and what precedence is
        # set. Therefore, first add all RTL into a dictionary and
        # later place it in the right order.
        #
        # Check if hardware has precedence (default `precedence = sw`)
        if self.obj.get_property('precedence') == PrecedenceType.sw:
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
        abort_set = False

        for i in order_list:
            # Still a loop and not a list comprehension since this might
            # get longer in the future and thus become unreadable

            # First check if we need to break or continue the loop
            if abort_set:
                break

            # Check if there is a list that shall be unlooped
            if isinstance(self.access_rtl[i], tuple):
                access_rtl = [self.access_rtl[i]]
            else:
                access_rtl = self.access_rtl[i]

            for unpacked_access_rtl in access_rtl:
                if len(unpacked_access_rtl[0]) == 0:
                    continue

                order_list_rtl = [*order_list_rtl, *unpacked_access_rtl[0]]
                order_list_rtl.append("else")

                # If the access_rtl entry has an abortion entry, do not print
                # any further branches of the conditional block
                abort_set = unpacked_access_rtl[1]

        # Remove last else
        order_list_rtl.pop()

        # Chain access RTL to the rest of the RTL
        self.rtl_header = [*self.rtl_header, *order_list_rtl]

        self.rtl_header.append(
            self.process_yaml(
                Field.templ_dict['end_field_ff'],
                {'path': self.path_underscored}
            )
        )


    def __add_combo(self):
        operations = []
        if self.obj.get_property('anded'):
            operations.append(['&', 'assign_anded_operation'])
        if self.obj.get_property('ored'):
            operations.append(['|', 'assign_ored_operation'])
        if self.obj.get_property('xored'):
            operations.append(['^', 'assign_xored_operation'])

        if len(operations) > 0:
            self.rtl_footer.append(
                self.process_yaml(
                    Field.templ_dict['combo_operation_comment'],
                    {'path': self.path_underscored}
                )
            )

        self.rtl_footer = [
            *self.rtl_footer,
            *[self.process_yaml(
                Field.templ_dict[i[1]],
                {'path': self.path_underscored,
                 'genvars': self.genvars_str,
                 'op_verilog': i[0],
                 'field_type': self.field_type}
            ) for i in operations]
            ]


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
            self.field_type = 'logic [{}:0]'.format(self.obj.width-1)

    def __process_variables(self, obj: FieldNode, array_dimensions: list, glbl_settings: dict):
        # Create full name
        self.path_wo_field = '__'.join(self.path.split('.', -1)[0:-1])

        # Save dimensions of unpacked dimension
        self.array_dimensions = array_dimensions
        self.total_array_dimensions = array_dimensions
        self.total_dimensions = len(self.total_array_dimensions)

        # Calculate how many genvars shall be added
        genvars = ['[{}]'.format(chr(97+i)) for i in range(len(array_dimensions))]
        self.genvars_str = ''.join(genvars)

        # Write enable
        self.we_or_wel = self.obj.get_property('we') or self.obj.get_property('wel')

        # Save byte boundaries
        self.lsbyte = math.floor(obj.inst.lsb / 8)
        self.msbyte = math.floor(obj.inst.msb / 8)
        self.msb = obj.inst.msb
        self.lsb = obj.inst.lsb

        # Set that tells which hierarchies can read this field
        self.readable_by = set()

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

        # Define dict that holds all RTL
        self.access_rtl = dict()
        self.access_rtl['else'] = (["else"], False)
        self.access_rtl[''] = ([''], False)

    def summary(self):
        # Additional flags that are set
        misc_flags = set(self.obj.list_properties())

        # Remove some flags that are not interesting
        # or that are listed elsewhere
        misc_flags.discard('hw')
        misc_flags.discard('reset')

        precedence = self.obj.get_property('precedence')

        # Add comment with summary on field's properties
        return \
            Field.templ_dict['field_comment']['rtl'].format(
                name = self.name,
                hw_access = str(self.obj.get_property('hw'))[11:],
                sw_access = str(self.obj.get_property('sw'))[11:],
                hw_precedence = '(precedence)' if precedence == PrecedenceType.hw else '',
                sw_precedence = '(precedence)' if precedence == PrecedenceType.sw else '',
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
            self.process_yaml(
                Field.templ_dict[sense_list],
                {'rst_edge': self.rst['edge'],
                 'rst_name': self.rst['name']}
            )
        )

        # Add actual reset line
        if self.rst['name']:
            self.rtl_header.append(
                self.process_yaml(
                    Field.templ_dict['rst_field_assign'],
                    {'path': self.path_underscored,
                     'rst_name': self.rst['name'],
                     'rst_negl':  "!" if self.rst['active'] == "active_low" else "",
                     'rst_value': self.rst['value'],
                     'genvars': self.genvars_str,
                     'field_type': self.field_type}
                )
            )

        self.rtl_header.append("begin")

        # Add name of actual field to Signal field
        # TODO

    def sanity_checks(self):
        # If hw=rw/sw=[r]w and hw has no we/wel, sw will never be able to write
        if not self.we_or_wel and\
                self.obj.get_property('precedence') == PrecedenceType.hw and \
                self.obj.get_property('hw') in (AccessType.rw, AccessType.w) and \
                self.obj.get_property('sw') in (AccessType.rw, AccessType.w):

            self.logger.warning("Fields with hw=rw/sw=[r]w, we/wel not set and "\
                                "precedence for hardware will render software's "\
                                "write property useless since hardware will "\
                                "write every cycle.")


            # TODO: Counter & hw=r shouldn't work
