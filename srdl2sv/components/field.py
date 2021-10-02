import math

import importlib.resources as pkg_resources
import sys
import yaml

from systemrdl.node import FieldNode, SignalNode
from systemrdl.component import Reg, Regfile, Addrmap, Root
from systemrdl.rdltypes import PrecedenceType, AccessType, OnReadType, OnWriteType, InterruptType

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
        if not self.config['external']:
            self.__add_always_ff()

            # Only add normal hardware access if field is not an interrupt field
            if not self.__add_interrupt():
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
            # Append to list of registers that can write
            self.writable_by.add(path_wo_field)

            # This will need a wire to indicate that a write is taking place
            self.properties['sw_wr_wire'] = True
            self.properties['sw_wr'] = True

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
                    self.logger.warning("The OnWriteType.wuser is not yet supported!")
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
                    for i in range(self.lsbyte, self.msbyte+1):
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

            self.properties['sw_wr'] = True

            # Set onread properties
            if onread == OnReadType.ruser:
                self.logger.error("The OnReadType.ruser is not yet supported!")
            elif onread:
                self.properties['sw_rd_wire'] = True

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

        self.path_underscored_vec.append(path_underscored)
        self.path_wo_field_vec.append(path_wo_field)

    def __add_counter(self):
        if self.obj.get_property('counter'):
            self.logger.debug("Detected counter property")

            self.rtl_footer.append(Field.templ_dict['counter_comment']['rtl'])

            # Determine saturation values
            if isinstance(self.obj.get_property('incrsaturate'), bool):
                if self.obj.get_property('incrsaturate'):
                    incr_sat_value = 2**self.obj.width-1
                    overflow_value = incr_sat_value
                else:
                    incr_sat_value = False
                    overflow_value = 2**self.obj.width-1
            else:
                incr_sat_value = self.obj.get_property('incrsaturate')
                overflow_value = incr_sat_value

            if isinstance(self.obj.get_property('decrsaturate'), bool):
                if self.obj.get_property('decrsaturate'):
                    decr_sat_value = 0
                    underflow_value = decr_sat_value
                else:
                    decr_sat_value = False
                    underflow_value = 0
            else:
                decr_sat_value = self.obj.get_property('decrsaturate')
                underflow_value = decr_sat_value

            # Determine threshold values
            if isinstance(self.obj.get_property('incrthreshold'), bool):
                if self.obj.get_property('incrthreshold'):
                    incr_thr_value = 2**self.obj.width-1
                else:
                    incr_thr_value = False
            else:
                incr_thr_value = self.obj.get_property('incrthreshold')

            if isinstance(self.obj.get_property('decrthreshold'), bool):
                if self.obj.get_property('decrthreshold'):
                    decr_thr_value = 2**self.obj.width-1
                else:
                    decr_thr_value = False
            else:
                decr_thr_value = self.obj.get_property('decrthreshold')

            # Determine with what value the counter is incremented
            # According to the spec, the incrvalue/decrvalue default to '1'
            obj_incr_value = self.obj.get_property('incrvalue')
            obj_decr_value = self.obj.get_property('decrvalue')
            obj_incr_width = self.obj.get_property('incrwidth')
            obj_decr_width = self.obj.get_property('decrwidth')

            incr_width_input = False

            if obj_incr_value == 0:
                incr_value = 0
                incr_width = 1
            elif obj_incr_value is None:
                # Increment value is not set. Check if incrwidth is set and use
                # that is applicable
                if obj_incr_width:
                    incr_value = False
                    incr_width = obj_incr_width

                    incr_width_input = True

                    # Doesn't return RTL, only adds input port
                    self.process_yaml(
                        Field.templ_dict['counter_incr_val_input'],
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
                # An explicit width is set for the incr_val
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


            # If no input is defined for the increment value, define
            # an internal signal. It is possible that this is tied to 0.
            if not incr_width_input:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_incr_val_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width-1,
                         'incr_value': incr_value,
                        }
                    )
                )

            # Handle decrement value
            decr_width_input = False

            if obj_decr_value == 0:
                decr_value = 0
                decr_width = 1
            elif obj_incr_value is None:
                # Decrement value is not set. Check if decrwidth is set and use
                # that is applicable
                if obj_decr_width:
                    decr_value = False
                    decr_width = obj_decr_width

                    decr_width_input = True

                    # Doesn't return RTL, only adds input port
                    self.process_yaml(
                        Field.templ_dict['counter_decr_val_input'],
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
                # An explicit width is set for the decr_val
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


            # If no input is defined for the decrement value, define
            # an internal signal. It is possible that this is tied to 0.
            if not decr_width_input:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_decr_val_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'decr_width': decr_width-1,
                         'decr_value': decr_value,
                        }
                    )
                )

            # Handle the increment/decrement signals.
            # If the increment or decrement signal is not set, use an input
            # if the decrement value is bigger than 0
            if not incr_value and not decr_value:
                self.logger.fatal("Illegal counter configuration! Both 'incr_value' "\
                                  "and 'decr_value' are forced to 0. If you intended "\
                                  "to use 'incr_width' or 'decr_width', simply don't "\
                                  "force 'incr_value' or 'decr_value' to any value.")
                sys.exit(1)

            if incr_value:
                incr = self.obj.get_property('incr')

                if not incr:
                    # Will only add input port but not return any RTL
                    self.process_yaml(
                        Field.templ_dict['counter_incr_input'],
                        {'path': self.path_underscored}
                    )
                else:
                    self.rtl_footer.append(
                        self.process_yaml(
                            Field.templ_dict['counter_internal_incr_signal'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'incr': self.get_signal_name(incr)
                            }
                        )
                    )

                    try:
                        if incr.width > 0:
                            self.logger.error("Increment signal '{}' is wider than 1-bit. "\
                                              "This might result in unwanted behavior and "\
                                              "will also cause Lint-errors.".format(
                                                  incr.inst_name))
                    except AttributeError:
                        # 'PropRef_overflow' object has no attribute 'width'
                        pass
            else:
                # Tie signal to 0
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_incr_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr': '0'
                        }
                    )
                )

            if decr_value:
                decr = self.obj.get_property('decr')

                if not self.obj.get_property('decr'):
                    # Will only add input port but not return any RTL
                    self.process_yaml(
                        Field.templ_dict['counter_decr_input'],
                        {'path': self.path_underscored}
                    )
                else:
                    self.rtl_footer.append(
                        self.process_yaml(
                            Field.templ_dict['counter_internal_decr_signal'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'decr': self.get_signal_name(decr)
                            }
                        )
                    )

                    try:
                        if decr.width > 0:
                            self.logger.error("Decrement signal '{}' is wider than 1-bit. "\
                                              "This might result in unwanted behavior and "\
                                              "will also cause Lint-errors.".format(
                                                  decr.inst_name))
                    except AttributeError:
                        # 'PropRef_underflow' object has no attribute 'width'
                        pass
            else:
                # Tie signal to 0
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_internal_decr_signal'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'decr': '0'
                        }
                    )
                )

            # Handle saturation signals
            if not incr_sat_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_incr_sat_tied'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                )
            else:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_incr_sat'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'sat_value': incr_sat_value,
                        }
                    )
                )

            if not decr_sat_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_decr_sat_tied'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                )
            else:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_decr_sat'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'sat_value': decr_sat_value,
                        }
                    )
                )

            # Handle threshold values
            if incr_thr_value or decr_thr_value:
                self.rtl_footer.append(Field.templ_dict['counter_thr_comment']['rtl'])

            if incr_thr_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_incr_thr'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'thr_value': incr_thr_value,
                        }
                    )
                )

            if decr_thr_value:
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_decr_thr'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'thr_value': decr_thr_value,
                        }
                    )
                )

            # Handle overflow & underflow signals
            if self.obj.get_property('overflow'):
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_overflow'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'overflow_value': overflow_value,
                        }
                    )
                )

            if self.obj.get_property('underflow'):
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict['counter_underflow'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'incr_width': incr_width,
                         'decr_width': decr_width,
                         'underflow_value': underflow_value,
                        }
                    )
                )

            # Implement actual counter logic
            self.rtl_footer.append(
                self.process_yaml(
                    Field.templ_dict['counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
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
            if self.properties['sw_wr']:
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
                (self.properties['sw_rd'] or self.properties['sw_wr']):
            self.logger.debug("Field has swacc property")

            self.properties['swacc'] = True
            self.properties['sw_wr_wire'] = True
            self.properties['sw_rd_wire'] = True

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

    def __add_interrupt(self):
        if self.obj.get_property('intr'):
            self.properties['intr'] = True

            # Determine what causes the interrupt to get set, i.e.,
            # is it a trigger that is passed to the module through an
            # input or is it an internal signal
            if next_val := self.obj.get_property('next'):
                intr_trigger = self.get_signal_name(next_val)
            else:
                intr_trigger = \
                    self.process_yaml(
                        Field.templ_dict['interrupt_trigger_input'],
                        {'path': self.path_underscored}
                    )

            if self.obj.get_property('stickybit'): 
                self.access_rtl['hw_write'] = ([
                    self.process_yaml(
                        Field.templ_dict['sticky_intr'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                ],
                False)

                # Create logic that contains condition for trigger
                if self.obj.get_property('intr type') != InterruptType.level:
                    if self.rst['name']:
                        reset_intr_header = \
                            self.process_yaml(
                                Field.templ_dict['rst_intr_header'],
                                {'interrupt_trigger_input': intr_trigger,
                                 'rst_name': self.rst['name'],
                                 'rst_negl':  "!" if self.rst['active'] == "active_low" else "",
                                 'genvars': self.genvars_str,
                                }
                            )
                    else:
                        reset_intr_header = ""

                    self.rtl_footer.append(
                        self.process_yaml(
                            Field.templ_dict['always_ff_block_intr'],
                            {'interrupt_trigger_input': intr_trigger,
                             'always_ff_header': self.always_ff_header,
                             'reset_intr_header': reset_intr_header,
                             'genvars': self.genvars_str,
                            }
                        )
                    )

                # This should be implemented as a match case statement later,
                # but for now use the old if/elif/else construct to ensure
                # compatibility with Python versions before 2021
                self.rtl_footer.append(
                    self.process_yaml(
                        Field.templ_dict[str(self.obj.get_property('intr type'))],
                        {'interrupt_trigger_input': intr_trigger,
                         'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                )


            else:
                self.access_rtl['hw_write'] = ([
                    self.process_yaml(
                        Field.templ_dict['nonsticky_intr'],
                        {'path': self.path_underscored,
                         'assignment': intr_trigger,
                         'genvars': self.genvars_str,
                        }
                    )
                ],
                False)

            # Generate masked & enabled version of interrupt to be
            # picked up by the register at the top level
            if mask := self.obj.get_property('mask'):
                self.itr_masked = ' && !'.join([
                    self.register_name,
                    self.get_signal_name(mask)
                ])
            elif enable := self.obj.get_property('enable'):
                self.itr_masked = ' && '.join([
                    self.register_name,
                    self.get_signal_name(enable)
                ])
            else:
                self.itr_masked = self.register_name

            # Generate haltmasked & haltenabled version of interrupt to be
            # picked up by the register at the top level
            if haltmask := self.obj.get_property('haltmask'):
                self.itr_haltmasked = ' && !'.join([
                    self.register_name,
                    self.get_signal_name(haltmask)
                ])

                self.properties['halt'] = True
            elif haltenable := self.obj.get_property('haltenable'):
                self.itr_haltmasked = ' && '.join([
                    self.register_name,
                    self.get_signal_name(haltenable)
                ])

                self.properties['halt'] = True
            else:
                self.itr_haltmasked = self.register_name
        else:
            self.itr_masked = False
            self.itr_haltmasked = False

        return self.properties['intr']

    def __add_hw_access(self):
        # Mutually exclusive. systemrdl-compiler performs check for this
        enable_mask_negl = ''
        enable_mask = False

        if self.obj.get_property('hwenable'):
            enable_mask = self.obj.get_property('hwenable')
        elif self.obj.get_property('hwmask'):
            enable_mask = self.obj.get_property('hwmask')
            enable_mask_negl = '!'

        if enable_mask:
            enable_mask_start_rtl = \
                self.process_yaml(
                    Field.templ_dict['hw_enable_mask_start'],
                    {'signal': self.get_signal_name(enable_mask),
                     'width': self.obj.width,
                     'negl': enable_mask_negl}
                )

            enable_mask_end_rtl = \
                self.process_yaml(
                    Field.templ_dict['hw_enable_mask_end'],
                    {'width': self.obj.width}
                )

            enable_mask_idx = '[idx]'
        else:
            enable_mask_start_rtl = '<<SQUASH_NEWLINE>>'
            enable_mask_end_rtl = '<<SQUASH_NEWLINE>>'
            enable_mask_idx = ''

        # Define hardware access (if applicable)
        if self.obj.get_property('counter'):
            self.access_rtl['hw_write'] = ([
                self.process_yaml(
                    Field.templ_dict['hw_access_counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'field_type': self.field_type,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'idx': enable_mask_idx}
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
            if self.obj.get_property('next'):
                # 'next' property is used
                self.logger.debug("Found property 'next'")

                assignment = self.get_signal_name(self.obj.get_property('next'))

                skip_inputs = True

                if self.we_or_wel:
                    self.logger.info("This field has a 'we' or 'wel' property and "
                                     "uses the 'next' property. Make sure this is "
                                     "is intentional.")
            else:
                skip_inputs = False

                # No special property. Assign input to register
                assignment = \
                    self.process_yaml(
                        Field.templ_dict['hw_access_field__assignment__input'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'idx': enable_mask_idx,
                         'field_type': self.field_type}
                    )

            self.access_rtl['hw_write'][0].append(
                self.process_yaml(
                    Field.templ_dict['hw_access_field'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'assignment': assignment,
                     'idx': enable_mask_idx,
                     'field_type': self.field_type},
                    skip_inputs = skip_inputs
                )
            )
        else:
            self.access_rtl['hw_write'] = ([], False)

        # Check if the hwset or hwclr option is set
        if self.obj.get_property('hwset'):
            self.access_rtl['hw_setclr'] = ([
                self.process_yaml(
                    Field.templ_dict['hw_access_hwset'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'idx': enable_mask_idx,
                     'constant': "{{{}{{1'b1}}}}".format(self.obj.width)
                        if not enable_mask else "1'b1"
                    }
                )
            ],
            False)
        elif self.obj.get_property('hwclr'):
            self.access_rtl['hw_setclr'] = ([
                self.process_yaml(
                    Field.templ_dict['hw_access_hwclr'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'idx': enable_mask_idx,
                     'constant': "{{{}{{1'b0}}}}".format(self.obj.width)
                        if not enable_mask else "1'b0"
                    }
                )
            ],
            False)
        else:
            self.access_rtl['hw_setclr'] = ([], False)

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

    def create_external_rtl(self):
        if self.properties['sw_wr']:
            for i, alias in enumerate(self.path_underscored_vec):
                # Create bit-wise mask so that outside logic knows what
                # bits it may change
                mask = []
                for j, byte_idx in enumerate(range(self.msbyte, self.lsbyte-1, -1)):
                    if byte_idx == self.lsbyte:
                        width = (self.lsbyte+1)*8 - self.lsb
                    elif byte_idx == self.msbyte:
                        width = 8 - ((self.msbyte+1)*8-1 - self.msb)
                    else:
                        width = 8

                    mask.append(
                        Field.templ_dict['external_wr_mask_segment']['rtl'].format(
                            idx = byte_idx,
                            width = width)
                        )

                self.rtl_footer.append(self.process_yaml(
                    Field.templ_dict['external_wr_assignments'],
                    {'path': alias,
                     'path_wo_field': self.path_wo_field_vec[i],
                     'genvars': self.genvars_str,
                     'msb_bus': self.msb,
                     'lsb_bus': self.lsb,
                     'mask': ','.join(mask),
                     'width': self.obj.width-1,
                     'field_type': self.field_type
                    }
                ))

        if self.properties['sw_rd']:
            for i, alias in enumerate(self.path_underscored_vec):
                self.rtl_footer.append(self.process_yaml(
                    Field.templ_dict['external_rd_assignments'],
                    {'path': alias,
                     'path_wo_field': self.path_wo_field_vec[i],
                     'genvars': self.genvars_str,
                     'field_type': self.field_type
                    }
                ))

    def create_internal_rtl(self):
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
                'hw_setclr',
                'singlepulse'
                ]
        else:
            order_list = [
                'hw_write',
                'hw_setclr',
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
            try:
                if isinstance(self.access_rtl[i], tuple):
                    access_rtl = [self.access_rtl[i]]
                else:
                    access_rtl = self.access_rtl[i]
            except KeyError:
                continue

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
        self.register_name = ''.join([self.path_underscored, '_q'])

        self.path_underscored_vec = []
        self.path_wo_field_vec = []

        # Save dimensions of unpacked dimension
        self.array_dimensions = array_dimensions
        self.total_array_dimensions = array_dimensions
        self.total_dimensions = len(self.total_array_dimensions)

        # Calculate how many genvars shall be added
        genvars = ['[gv_{}]'.format(chr(97+i)) for i in range(len(array_dimensions))]
        self.genvars_str = ''.join(genvars)

        # Write enable
        self.we_or_wel = self.obj.get_property('we') or self.obj.get_property('wel')

        # Save byte boundaries
        self.lsbyte = math.floor(obj.inst.lsb / 8)
        self.msbyte = math.floor(obj.inst.msb / 8)
        self.msb = obj.inst.msb
        self.lsb = obj.inst.lsb

        # Set that tells which hierarchies can read/write this field
        self.readable_by = set()
        self.writable_by = set()

        # Determine resets. This includes checking for async/sync resets,
        # the reset value, and whether the field actually has a reset
        self.rst = Field.process_reset_signal(
                        obj.get_property("resetsignal"))

        if self.rst['name']:
            self.resets.add(self.rst['name'])
        elif obj.get_property("reset") is not None:
            self.logger.warning("Field has a reset value, but no reset "\
                                "signal was defined and connected to the "\
                                "field. Note that explicit connecting this "\
                                "is not required if a field_reset was defined.")

        # Value of reset must always be determined on field level
        # Don't use 'not obj.get_property("reset"), since the value
        # could (and will often be) be '0'
        self.rst['value'] = \
            '\'x' if obj.get_property("reset") == None else\
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
                external = self.config['external'],
                lsb = self.obj.lsb,
                msb = self.obj.msb,
                path_wo_field = self.path_wo_field)

    def __add_always_ff(self):
        # Handle always_ff
        sense_list = 'sense_list_rst' if self.rst['async'] else 'sense_list_no_rst'

        self.always_ff_header = \
            self.process_yaml(
                Field.templ_dict[sense_list],
                {'rst_edge': self.rst['edge'],
                 'rst_name': self.rst['name']}
            )

        self.rtl_header.append(self.always_ff_header)

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


        # If hw=ro and the next property is set, throw a fatal
        if self.obj.get_property('hw') == AccessType.r\
                and self.obj.get_property('next'):
            self.logger.error("Hardware property of field is set to read-only "\
                              "but simultanously, the next property is set. Since "\
                              "this would reflect wrong behavior in documentation, "\
                              "the next property is ignored.")
