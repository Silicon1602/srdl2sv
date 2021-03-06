import math

import importlib.resources as pkg_resources
import sys
from typing import Optional
from enum import Enum
import yaml

from systemrdl.node import FieldNode, SignalNode
from systemrdl.component import Reg, Regfile
from systemrdl.rdltypes import PrecedenceType, AccessType, OnReadType, OnWriteType, InterruptType

# Local modules
from srdl2sv.components.component import Component, TypeDef
from srdl2sv.components import templates

class StorageType(Enum):
    FLOPS = 0
    WIRE = 1
    CONST = 2

class Field(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'fields.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: FieldNode,
            parents_dimensions: Optional[list],
            config: dict):
        super().__init__(
                    obj=obj,
                    config=config,
                    parents_strides=None,
                    parents_dimensions=parents_dimensions)

        # Generate all variables that have anything to do with dimensions or strides
        self._init_genvars()

        # Save and/or process important variables
        self.__init_variables(obj)

        # Determine whether it is a wire, flops, or a wire
        self.__init_storage_type()

        # Determine field types
        self.__init_fieldtype()

        ##################################################################################
        # LIMITATION:
        # v1.x of the systemrdl-compiler does not support non-homogeneous arrays.
        # It is planned, however, for v2.0.0 of the compiler. More information
        # can be found here: https://github.com/SystemRDL/systemrdl-compiler/issues/51
        ##################################################################################
        # Print a summary
        self.rtl_header.append(self.__summary())

        # Add description
        self.rtl_header.append(self.get_description())

        # HW Access can be handled in __init__ function but SW access
        # must be handled in a seperate method that can be called
        # seperately in case of alias registers
        if self.config['external']:
            pass
        elif self.storage_type is not StorageType.FLOPS:
            self.__add_wire_const()
            self.__add_hw_rd_access()
            self.__add_swmod_swacc()
        else:
            self.__add_always_ff()

            # Only add normal hardware access if field is not an interrupt field
            if not self.__add_interrupt():
                self.__add_hw_wr_access()
                self.__add_hw_rd_access()

            self.__add_combo()
            self.__add_swmod_swacc()
            self.__add_counter()

        self.add_sw_access(obj)

    def add_sw_access(self, obj, alias = False):

        # Perform some basic checks
        onwrite = obj.get_property('onwrite')
        onread = obj.get_property('onread')

        if onwrite and not self.properties['sw_wr']:
            self.logger.fatal("An onwrite property '%s' is defined but "\
                              "software does not have write-access. This is not "\
                              "legal.", onwrite)

            sys.exit(1)
        elif onread and self.storage_type is not StorageType.FLOPS:
            self.logger.warning("Field has an onread property '%s' but does not "
                                "implement a flop. Since the flop itself is "
                                "implemented outside of the register block it is "
                                "advised to remove the property and notify the external "
                                "hardware by using the 'swacc' property.", onread)

        access_rtl = {}

        if alias:
            _, _, path, alias_path_underscored = \
                Field.create_underscored_path_static(obj)
        else:
            path = self.path

        # This is different than self.path_underscored_wo_field
        path_underscored_wo_field = '__'.join(path.split('.', -1)[0:-1])

        # path_wo_field_vec & path_undrescored_vec only used for external registers
        self.path_wo_field_vec.append(path_underscored_wo_field)
        self.path_underscored_vec.append(alias_path_underscored if alias else self.path_underscored)

        # Define software access (if applicable)
        access_rtl['sw_write'] = ([], False)

        if self.properties['sw_wr']:
            # Append to list of registers that can write
            self.writable_by.add(path_underscored_wo_field)

            # This will need a wire to indicate that a write is taking place
            self.properties['sw_wr_wire'] = True

            swwe = obj.get_property('swwe')
            swwel = obj.get_property('swwel')

            if isinstance(swwe, (FieldNode, SignalNode)):
                access_rtl['sw_write'][0].append(
                    self._process_yaml(
                        Field.templ_dict['sw_access_field_swwe'],
                        {'path_wo_field': path_underscored_wo_field,
                         'genvars': self.genvars_str,
                         'swwe': self.get_signal_name(swwe),
                         'field_type': self.field_type}
                    )
                )
            elif isinstance(swwel, (FieldNode, SignalNode)):
                access_rtl['sw_write'][0].append(
                    self._process_yaml(
                        Field.templ_dict['sw_access_field_swwel'],
                        {'path_wo_field': path_underscored_wo_field,
                         'genvars': self.genvars_str,
                         'swwel': self.get_signal_name(swwel),
                         'field_type': self.field_type}
                    )
                )
            else:
                access_rtl['sw_write'][0].append(
                    self._process_yaml(
                        Field.templ_dict['sw_access_field'],
                        {'path_wo_field': path_underscored_wo_field,
                         'genvars': self.genvars_str,
                         'field_type': self.field_type}
                    )
                )

            # Check if an onwrite property is set
            if onwrite := obj.get_property('onwrite'):
                if onwrite is OnWriteType.wuser:
                    self.logger.error("The OnWriteType.wuser is not yet supported!")
                else:
                    # If field spans multiple bytes, every byte shall have a seperate enable!
                    for i in range(self.lsbyte, self.msbyte+1):
                        msb_bus = 8*(i+1)-1 if i != self.msbyte else obj.msb
                        lsb_bus = 8*i if i != self.lsbyte else obj.inst.lsb

                        access_rtl['sw_write'][0].append(
                            self._process_yaml(
                                Field.templ_dict[str(onwrite)],
                                {'path': self.path_underscored,
                                 'genvars': self.genvars_str,
                                 'i': i,
                                 'width': msb_bus - lsb_bus + 1,
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
                for i in range(self.lsbyte, self.msbyte+1):
                    msb_bus = 8*(i+1)-1 if i != self.msbyte else obj.msb
                    lsb_bus = 8*i if i != self.lsbyte else obj.inst.lsb

                    access_rtl['sw_write'][0].append(
                        self._process_yaml(
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

        access_rtl['sw_read'] = ([], False)

        if obj.get_property('sw') in (AccessType.rw, AccessType.r):
            # Append to list of registers that can read
            self.readable_by.add(path_underscored_wo_field)

            self.properties['sw_rd'] = True

            # Set onread properties
            if onread is OnReadType.ruser:
                self.logger.error("The OnReadType.ruser is not yet supported!")
            elif onread and self.storage_type is StorageType.FLOPS:
                self.properties['sw_rd_wire'] = True

                access_rtl['sw_read'][0].append(
                    self._process_yaml(
                        Field.templ_dict['sw_read_access_field'],
                        {'path_wo_field': path_underscored_wo_field,
                         'genvars': self.genvars_str,
                         'field_type': self.field_type}
                    )
                )

                # If field spans multiple bytes, every byte shall have a seperate enable!
                for i in range(self.lsbyte, self.msbyte+1):
                    access_rtl['sw_read'][0].append(
                        self._process_yaml(
                            Field.templ_dict[str(onread)],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'i': i,
                             'width': msb_bus - lsb_bus + 1,
                             'msb_field': str(msb_bus-obj.inst.lsb),
                             'lsb_field': str(lsb_bus-obj.inst.lsb),
                            }
                        )
                    )

                access_rtl['sw_read'][0].append("end")

        # Add singlepulse property
        # Property cannot be overwritten by alias
        if obj.get_property('singlepulse'):
            self.access_rtl['singlepulse'] = ([
                self._process_yaml(
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

            self.rtl_footer.append(Field.templ_dict['counter_comment']['rtl'])

            # Determine saturation values
            if isinstance(saturate := self.obj.get_property('incrsaturate'), bool):
                if saturate:
                    incr_sat_value = f"{self.obj.width}'d{2**self.obj.width-1}"
                    overflow_value = incr_sat_value
                else:
                    incr_sat_value = False
                    overflow_value = 2**self.obj.width-1
            elif isinstance(saturate, int):
                incr_sat_value = f"{self.obj.width}'d{saturate}"
                underflow_value = incr_sat_value
            else:
                incr_sat_value = self.get_signal_name(saturate)
                overflow_value = incr_sat_value

            if isinstance(saturate := self.obj.get_property('decrsaturate'), bool):
                if saturate:
                    decr_sat_value = f"{self.obj.width}'d0"
                    underflow_value = decr_sat_value
                else:
                    decr_sat_value = False
                    underflow_value = 0
            elif isinstance(saturate, int):
                decr_sat_value = f"{self.obj.width}'d{saturate}"
                underflow_value = decr_sat_value
            else:
                decr_sat_value = self.get_signal_name(saturate)
                underflow_value = decr_sat_value

            # Determine threshold values
            if isinstance(threshold := self.obj.get_property('incrthreshold'), bool):
                if threshold:
                    incr_thr_value = f"{self.obj.width}'d{2**self.obj.width-1}"
                else:
                    incr_thr_value = False
            elif isinstance(threshold, int):
                incr_thr_value = f"{self.obj.width}'d{threshold}"
            else:
                incr_thr_value = self.get_signal_name(threshold)

            if isinstance(threshold := self.obj.get_property('decrthreshold'), bool):
                if threshold:
                    decr_thr_value = f"{self.obj.width}'d{2**self.obj.width-1}"
                else:
                    decr_thr_value = False
            elif isinstance(threshold, int):
                decr_thr_value = f"{self.obj.width}'d{threshold}"
            else:
                decr_thr_value = self.get_signal_name(threshold)

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
                    self._process_yaml(
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
                        "The 'incrwidth' and 'incrvalue' properties are both "
                        "defined. This is not legal and the incrwidth property "
                        "will be ignored!")
            else:
                incr_value = self.get_signal_name(obj_incr_value)
                incr_width = obj_incr_value.width

                if obj_incr_value.width > self.obj.width:
                    self.logger.error(
                        "Width of 'incr_value' signal '%s' is wider than current counter"
                        "field. This could potentiall cause ugly errors.",
                        obj_incr_value.get_path())

                if obj_incr_width:
                    self.logger.error(
                        "The 'incrwidth' and 'incrvalue' properties are both "
                        "defined. This is not legal and the incrwidth property "
                        "will be ignored!")


            # If no input is defined for the increment value, define
            # an internal signal. It is possible that this is tied to 0.
            if not incr_width_input:
                self.rtl_footer.append(
                    self._process_yaml(
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
                    self._process_yaml(
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
                        "The 'decrwidth' and 'decrvalue' properties are both "
                        "defined. This is not legal and the decrwidth property "
                        "will be ignored!")
            else:
                decr_value = self.get_signal_name(obj_decr_value)
                decr_width = obj_decr_value.width

                if obj_decr_value.width > self.obj.width:
                    self.logger.error(
                        "Width of 'decr_value' signal '%s' is wider than current counter"
                        "field. This could potentiall cause ugly errors.",
                        obj_decr_value.get_path())

                if obj_decr_width:
                    self.logger.error(
                        "The 'decrwidth' and 'decrvalue' properties are both "
                        "defined. This is not legal and the decrwidth property "
                        "will be ignored!")

            # Calculate the number of bits that need to be padded with 0s
            if remaining_width := self.obj.width - incr_width:
                incr_zero_pad = f"{remaining_width}'b0, "
                incr_sat_zero_pad = f"{remaining_width+1}'b0, "
            else:
                incr_zero_pad = ""
                incr_sat_zero_pad = "1'b0"

            if remaining_width := self.obj.width - decr_width:
                decr_zero_pad = f"{remaining_width}'b0, "
                decr_sat_zero_pad = f"{remaining_width+1}'b0, "
            else:
                decr_zero_pad = ''
                decr_sat_zero_pad = "1'b0"

            # If no input is defined for the decrement value, define
            # an internal signal. It is possible that this is tied to 0.
            if not decr_width_input:
                self.rtl_footer.append(
                    self._process_yaml(
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
                    self._process_yaml(
                        Field.templ_dict['counter_incr_input'],
                        {'path': self.path_underscored}
                    )
                else:
                    self.rtl_footer.append(
                        self._process_yaml(
                            Field.templ_dict['counter_internal_incr_signal'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'incr': self.get_signal_name(incr)
                            }
                        )
                    )

                    try:
                        if incr.width > 0:
                            self.logger.error(
                                "Increment signal '%s' is wider than 1 bit. This might"
                                "result in unwanted behavior and will also cause Lint-errors.",
                                incr.inst_name)
                    except AttributeError:
                        # 'PropRef_overflow' object has no attribute 'width'
                        pass
            else:
                # Tie signal to 0
                self.rtl_footer.append(
                    self._process_yaml(
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
                    self._process_yaml(
                        Field.templ_dict['counter_decr_input'],
                        {'path': self.path_underscored}
                    )
                else:
                    self.rtl_footer.append(
                        self._process_yaml(
                            Field.templ_dict['counter_internal_decr_signal'],
                            {'path': self.path_underscored,
                             'genvars': self.genvars_str,
                             'decr': self.get_signal_name(decr)
                            }
                        )
                    )

                    try:
                        if decr.width > 0:
                            self.logger.error(
                                "Decrement signal '%s' is wider than 1 bit. This might"
                                "result in unwanted behavior and will also cause Lint-errors.",
                                decr.decr_name)
                    except AttributeError:
                        # 'PropRef_underflow' object has no attribute 'width'
                        pass
            else:
                # Tie signal to 0
                self.rtl_footer.append(
                    self._process_yaml(
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
                    self._process_yaml(
                        Field.templ_dict['counter_incr_sat_tied'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                )
            else:
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_incr_sat'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'sat_value': incr_sat_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': decr_sat_zero_pad,
                        }
                    )
                )

            if not decr_sat_value:
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_decr_sat_tied'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                        }
                    )
                )
            else:
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_decr_sat'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'sat_value': decr_sat_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': decr_sat_zero_pad,
                        }
                    )
                )

            # Handle threshold values
            if incr_thr_value or decr_thr_value:
                self.rtl_footer.append(Field.templ_dict['counter_thr_comment']['rtl'])

            if incr_thr_value:
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_incr_thr'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'thr_value': incr_thr_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': incr_sat_zero_pad,
                        }
                    )
                )

            if decr_thr_value:
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_decr_thr'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'thr_value': decr_thr_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': decr_sat_zero_pad,
                        }
                    )
                )

            # Handle overflow & underflow signals
            if self.obj.get_property('overflow'):
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_overflow'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'overflow_value': overflow_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': decr_sat_zero_pad,
                        }
                    )
                )

            if self.obj.get_property('underflow'):
                self.rtl_footer.append(
                    self._process_yaml(
                        Field.templ_dict['counter_underflow'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'underflow_value': underflow_value,
                         'width_plus_1': self.obj.width + 1,
                         'incr_sat_zero_pad': incr_sat_zero_pad,
                         'decr_sat_zero_pad': decr_sat_zero_pad,
                        }
                    )
                )

            # Implement actual counter logic
            self.rtl_footer.append(
                self._process_yaml(
                    Field.templ_dict['counter'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'incr_zero_pad': incr_zero_pad,
                     'decr_zero_pad': decr_zero_pad,
                    }
                )
            )

    def __add_swmod_swacc(self):
        if self.obj.get_property('swmod'):
            self.logger.debug("Field has swmod property")

            self.properties['swmod'] = True
            self.properties['sw_wr_wire'] = True

            swmod_assigns = []

            # Check if read side-effects are defined.
            if self.obj.get_property('onread'):
                swmod_assigns.append(
                    self._process_yaml(
                        Field.templ_dict['swmod_assign'],
                        {'path': self.path_underscored,
                         'path_wo_field': self.path_underscored_wo_field,
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
                    self._process_yaml(
                        Field.templ_dict['swmod_assign'],
                        {'path': self.path_underscored,
                         'path_wo_field': self.path_underscored_wo_field,
                         'genvars': self.genvars_str,
                         'rd_wr': 'wr',
                         'msbyte': self.msbyte,
                         'lsbyte': self.lsbyte,
                         'swmod_assigns': '\n'.join(swmod_assigns)
                        }
                    )
                )

            swmod_props = self._process_yaml(
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

            swacc_props = self._process_yaml(
                Field.templ_dict['swacc_assign'],
                {'path': self.path_underscored,
                 'path_wo_field': self.path_underscored_wo_field,
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

    def __add_sticky(self, latch_signal: str, force_trigger_generation: bool = False):
        bit_type = None
        trigger_signal = None

        if self.obj.get_property('stickybit'):
            bit_type = 'stickybit'
        elif self.obj.get_property('sticky'):
            bit_type = 'sticky'

        # Determine what causes the interrupt to get set, i.e.,
        # is it a trigger that is passed to the module through an
        # input or is it an internal signal
        if bit_type or force_trigger_generation:
            if next_val := self.obj.get_property('next'):
                trigger_signal = self.get_signal_name(next_val)
            else:
                trigger_signal =\
                    self._process_yaml(
                        Field.templ_dict['trigger_input'],
                        {'path': self.path_underscored,
                         'field_type': self.field_type,
                        }
                    )

        if bit_type:
            self.access_rtl['hw_write'] = ([
                self._process_yaml(
                    Field.templ_dict[bit_type],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'width': self.obj.width,
                     'field_type': self.field_type,
                     'trigger_signal': trigger_signal,
                    }
                )
            ],
            False)

            self.rtl_footer.append(
                self._process_yaml(
                    Field.templ_dict[str(latch_signal)],
                    {'trigger_signal': trigger_signal,
                     'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'field_type': self.field_type,
                    }
                )
            )

        return (bit_type, trigger_signal)

    def __add_interrupt(self):
        if self.obj.get_property('intr'):

            self.properties['intr'] = True

            intr_type = self.obj.get_property('intr type')

            # Check if it is a sticky(bit) interrupt and generate logic
            sticky_type, trigger_signal = self.__add_sticky(
                latch_signal = intr_type,
                force_trigger_generation = True)

            # Interrupts can have special types of sticky bits: posedge, negedge, bothedge.
            # Normal fields with the sticky(bit) property are always level.
            #
            # The actual sticky field already got generated in __add_sticky()
            if sticky_type:
                if self.obj.width > 1 \
                        and sticky_type == 'sticky' \
                        and intr_type in \
                            (InterruptType.posedge,
                             InterruptType.negedge,
                             InterruptType.bothedge):

                    self.logger.info(
                        "Found '%s' property for interrupt field that is "\
                        "wider than 1-bit and has the sticky (rather than the "\
                        "stickybit property. In this case, the value will be "\
                        "latched if _any_ bit in the signal changes according to "\
                        "'%s'",
                        intr_type,
                        intr_type
                    )

                if intr_type != InterruptType.level:
                    if self.rst['name']:
                        reset_intr_header = \
                            self._process_yaml(
                                Field.templ_dict['rst_intr_header'],
                                {'trigger_signal': trigger_signal,
                                 'rst_name': self.rst['name'],
                                 'rst_negl':  "!" if self.rst['active'] == "active_low" else "",
                                 'genvars': self.genvars_str,
                                 'field_type': self.field_type,
                                }
                            )
                    else:
                        reset_intr_header = ""

                    self.rtl_footer.append(
                        self._process_yaml(
                            Field.templ_dict['always_ff_block_intr'],
                            {'trigger_signal': trigger_signal,
                             'always_ff_header': self.always_ff_header,
                             'reset_intr_header': reset_intr_header,
                             'genvars': self.genvars_str,
                             'field_type': self.field_type,
                            }
                        )
                    )


            else:
                self.access_rtl['hw_write'] = ([
                    self._process_yaml(
                        Field.templ_dict['nonsticky_intr'],
                        {'path': self.path_underscored,
                         'assignment': trigger_signal,
                         'genvars': self.genvars_str,
                        }
                    )
                ],
                False)

            # Generate masked & enabled version of interrupt to be
            # picked up by the register at the top level
            if mask := self.obj.get_property('mask'):
                self.itr_masked = ' & ~'.join([
                    self.register_name,
                    self.get_signal_name(mask)
                ])
            elif enable := self.obj.get_property('enable'):
                self.itr_masked = ' & '.join([
                    self.register_name,
                    self.get_signal_name(enable)
                ])
            else:
                self.itr_masked = self.register_name

            # Generate haltmasked & haltenabled version of interrupt to be
            # picked up by the register at the top level
            if haltmask := self.obj.get_property('haltmask'):
                self.itr_haltmasked = ' & ~'.join([
                    self.register_name,
                    self.get_signal_name(haltmask)
                ])

                self.properties['halt'] = True
            elif haltenable := self.obj.get_property('haltenable'):
                self.itr_haltmasked = ' & ~'.join([
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

    def __add_wire_const(self):
        field_templ = 'hw_wire' if self.storage_type is StorageType.WIRE else 'hw_const'

        self.access_rtl['hw_write'] = ([
            self._process_yaml(
                Field.templ_dict[field_templ],
                {'path': self.path_underscored,
                 'genvars': self.genvars_str,
                 'field_type': self.field_type,
                 'width': self.obj.width,
                 'const': self.rst['value'],
                }
            )
        ],
        True)

    def __add_hw_wr_access(self):
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
                self._process_yaml(
                    Field.templ_dict['hw_enable_mask_start'],
                    {'signal': self.get_signal_name(enable_mask),
                     'width': self.obj.width,
                     'negl': enable_mask_negl}
                )

            enable_mask_end_rtl = \
                self._process_yaml(
                    Field.templ_dict['hw_enable_mask_end'],
                    {'width': self.obj.width}
                )

            enable_mask_idx = '[idx]'
        else:
            enable_mask_start_rtl = '<<SQUASH_NEWLINE>>'
            enable_mask_end_rtl = '<<SQUASH_NEWLINE>>'
            enable_mask_idx = ''

        # Define hardware access (if applicable)
        sticky, _ = self.__add_sticky(latch_signal = InterruptType.level)

        if sticky:
            self.logger.info("Found '%s' property.", sticky)
        elif self.obj.get_property('counter'):
            self.access_rtl['hw_write'] = ([
                self._process_yaml(
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
                self._process_yaml(
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
                    self._process_yaml(
                        Field.templ_dict['hw_access_field__assignment__input'],
                        {'path': self.path_underscored,
                         'genvars': self.genvars_str,
                         'idx': enable_mask_idx,
                         'field_type': self.field_type}
                    )

            self.access_rtl['hw_write'][0].append(
                self._process_yaml(
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
                self._process_yaml(
                    Field.templ_dict['hw_access_hwset'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'idx': enable_mask_idx,
                     'constant': f"{{{self.obj.width}{{1'b1}}}}"
                        if not enable_mask else "1'b1"
                    }
                )
            ],
            False)
        elif self.obj.get_property('hwclr'):
            self.access_rtl['hw_setclr'] = ([
                self._process_yaml(
                    Field.templ_dict['hw_access_hwclr'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'enable_mask_start': enable_mask_start_rtl,
                     'enable_mask_end': enable_mask_end_rtl,
                     'idx': enable_mask_idx,
                     'constant': f"{{{self.obj.width}{{1'b0}}}}"
                        if not enable_mask else "1'b0"
                    }
                )
            ],
            False)
        else:
            self.access_rtl['hw_setclr'] = ([], False)

    def __add_hw_rd_access(self):
        # Hookup flop to output port in case register is readable by hardware
        if self.obj.get_property('hw') in (AccessType.rw, AccessType.r):
            # Connect flops to output port
            self.rtl_footer.append(
                self._process_yaml(
                    Field.templ_dict['out_port_assign'],
                    {'genvars': self.genvars_str,
                     'path': self.path_underscored,
                     'field_type': self.field_type}
                )
            )

    def create_external_rtl(self):
        for i, alias in enumerate(self.path_underscored_vec):
            if self.properties['sw_wr']:
                # Create bit-wise mask so that outside logic knows what
                # bits it may change
                mask = []
                for byte_idx in range(self.msbyte, self.lsbyte-1, -1):
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

                wr_templ = 'external_wr_assignments' if i == 0 else 'external_wr_assignments_alias'

                self.rtl_footer.append(self._process_yaml(
                    Field.templ_dict[wr_templ],
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
                rd_templ = 'external_rd_assignments' if i == 0 else 'external_rd_assignments_alias'

                self.rtl_footer.append(self._process_yaml(
                    Field.templ_dict[rd_templ],
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
                'hw_setclr',
                'hw_write',
                'singlepulse'
                ]
        else:
            order_list = [
                'hw_setclr',
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

        if self.storage_type is StorageType.FLOPS:
            self.rtl_header.append(
                self._process_yaml(
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
                self._process_yaml(
                    Field.templ_dict['combo_operation_comment'],
                    {'path': self.path_underscored}
                )
            )

        self.rtl_footer = [
            *self.rtl_footer,
            *[self._process_yaml(
                Field.templ_dict[i[1]],
                {'path': self.path_underscored,
                 'genvars': self.genvars_str,
                 'op_verilog': i[0],
                 'field_type': self.field_type}
            ) for i in operations]
            ]

    def __init_fieldtype(self):
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

            self.logger.debug("Starting to parse '%s'", enum)

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
            #
            # If the field is multidimensional and packed arrays are turned off throw a
            # warning. Structures like:
            #
            #   input [N:0] enum_name   input_name,
            #
            # are not supported and this tool does not support custom datatypes where
            # packed dimensions are packed into another datatypes with the enum.
            #
            # For that reason, in such cases, a simple flat wire will be generated
            if self.total_dimensions > 0 and not self.config['unpacked_arrays']:
                self.logger.warning(
                    "Using multidimensional registers/regfiles with "
                    "enums and also using the option --no-unpacked "
                    "is only partly supported. Rather than using the enum "
                    "'%s', the flat wire with dimensions '[%i:0] will be used. "
                    "Note that the SystemVerilog package that holds the enum can "
                    "still be used.",
                    '::'.join(['_'.join([scope, 'pkg']), enum_name]),
                    self.obj.width-1)

                raise AttributeError

            self.field_type =\
                '::'.join(['_'.join([scope, 'pkg']), enum_name])

            self.logger.info("Parsed enum '%s'", enum_name)

        except AttributeError:
            # In case of an AttributeError, the encode property is None. Hence,
            # the field has a simple width
            self.field_type = f"logic [{self.obj.width-1}:0]"

    def __init_variables(
            self,
            obj: FieldNode):
        # Create full name
        self.path_underscored_wo_field = '__'.join(self.path.split('.', -1)[0:-1])
        self.register_name = ''.join([self.path_underscored, '_q'])

        self.path_underscored_vec = []
        self.path_wo_field_vec = []

        # Set some properties that always must be known
        self.properties['sw_wr'] = obj.get_property('sw') in (AccessType.rw, AccessType.w)
        self.properties['sw_rd'] = obj.get_property('sw') in (AccessType.rw, AccessType.r)

        # In case of an external register, a wire to indicate a read
        # is always required
        self.properties['sw_rd_wire'] = self.config['external'] and self.properties['sw_rd']

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
        self.rst = Field.__process_reset_signal(obj.get_property("resetsignal"))

        if self.rst['name']:
            self.resets.add(self.rst['name'])

        # Value of reset must always be determined on field level
        # Don't use 'not obj.get_property("reset"), since the value
        # could (and will often be) be '0'
        self.rst['value'] = \
            'x' if obj.get_property("reset") is None else\
                   obj.get_property('reset')

        # Define dict that holds all RTL
        self.access_rtl = {}
        self.access_rtl['else'] = (["else"], False)
        self.access_rtl[''] = ([''], False)

    def __init_storage_type(self):
        # It is not required to check for illegal conditions because the
        # compiler will take care of this
        hw_prop = self.obj.get_property('hw')
        sw_prop = self.obj.get_property('sw')

        # Check the storage type, according to Table 12 of the SystemRDL 2.0 LRM
        if self.obj.get_property('intr'):
            self.storage_type = StorageType.FLOPS
        elif hw_prop is AccessType.r and sw_prop is AccessType.r:
            # hw=r/sw=r --> Constant
            self.storage_type = StorageType.CONST
        elif hw_prop is AccessType.na and sw_prop is AccessType.r:
            # hw=na/sw=r --> Constant
            self.storage_type = StorageType.CONST
        elif hw_prop is AccessType.w and sw_prop is AccessType.r \
                and self.obj.get_property("reset") is None \
                and not self.we_or_wel:
            # If hw=w/sw=r AND no reset or we/wel is defined, a simple wire is implemented.
            # This isn't clear from Table 12, but '9.5.1 Semantics' describes this
            self.storage_type = StorageType.WIRE
        else:
            self.storage_type = StorageType.FLOPS

        self.logger.debug("Storage type of field detected as '%s'", self.storage_type)

    def __summary(self):
        # Additional flags that are set
        # Use list, rather than set, to ensure the order stays the same
        # when compiled multiple times
        misc_flags = list(self.obj.list_properties())

        # Remove some flags that are not interesting
        # or that are listed elsewhere
        for rdl_property in ('hw', 'reset'):
            try:
                misc_flags.remove(rdl_property)
            except ValueError:
                pass

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
                path_wo_field = self.path_underscored_wo_field,
                storage_type = self.storage_type,
            )

    def __add_always_ff(self):
        # Handle always_ff
        sense_list = 'sense_list_rst' if self.rst['async'] else 'sense_list_no_rst'

        self.always_ff_header = \
            self._process_yaml(
                Field.templ_dict[sense_list],
                {'rst_edge': self.rst['edge'],
                 'rst_name': self.rst['name']}
            )

        self.rtl_header.append(self.always_ff_header)

        # Add actual reset line
        if self.rst['name']:
            self.rtl_header.append(
                self._process_yaml(
                    Field.templ_dict['rst_field_assign'],
                    {'path': self.path_underscored,
                     'rst_name': self.rst['name'],
                     'rst_negl':  "!" if self.rst['active'] == "active_low" else "",
                     'rst_value': self.rst['value'],
                     'genvars': self.genvars_str,
                     'field_type': self.field_type,
                     'width': self.obj.width,
                    }
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

        # If a stick(bit) is defined, the counter property will be ignored
        if (self.obj.get_property('stickybit') or self.obj.get_property('sticky')) \
                and self.obj.get_property('counter'):
            self.logger.error("It's not possible to combine the sticky(bit) "\
                              "property with the counter property. The counter property "\
                              "will be ignored.")

        # If there a reset value is defined but no reset value, throw a warning
        # This is not true in case of a constant
        if not self.rst['name'] \
                and self.obj.get_property("reset") is not None \
                and self.storage_type is StorageType.FLOPS:
            self.logger.warning("Field has a reset value, but no reset "\
                                "signal was defined and connected to the "\
                                "field. Note that explicit connecting this "\
                                "is not required if a field_reset was defined.")

        if self.obj.get_property('counter') \
                and self.obj.get_property("reset") is None:
            self.logger.warning("Field is a counter but has no reset. "\
                                "This should probably be fixed since this "\
                                "will result in undefined behavior in simulations.")


    @staticmethod
    def __process_reset_signal(reset_signal):
        rst = {}

        try:
            rst['name']  = reset_signal.inst_name
            rst['async'] = reset_signal.get_property("async")
            rst['type'] = "asynchronous" if rst['async'] else "synchronous"

            # Active low or active high?
            if reset_signal.get_property("activelow"):
                rst['edge'] = "negedge"
                rst['active'] = "active_low"
            else:
                rst['edge'] = "posedge"
                rst['active'] = "active_high"
        except AttributeError:
            # Catch if reset_signal does not exist
            rst['async'] = False
            rst['name'] = None
            rst['edge'] = None
            rst['value'] = "x"
            rst['active'] = "-"
            rst['type'] = "-"

        return rst

