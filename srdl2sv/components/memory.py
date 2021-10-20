import re
import importlib.resources as pkg_resources
import sys
import math
import yaml

from systemrdl import node
from systemrdl.node import FieldNode
from systemrdl.rdltypes import AccessType

# Local packages
from components.component import Component, SWMuxEntry, SWMuxEntryDimensioned
from . import templates


class Memory(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'memory.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegfileNode,
            parents_dimensions: list,
            parents_stride: list,
            config: dict, 
            glbl_settings: dict):
        super().__init__(obj, config)

        # Save and/or process important variables
        self.__process_variables(obj, parents_dimensions, parents_stride, glbl_settings)

        # Set object to 0 for easy addressing
        self.obj.current_idx = [0]

        # When in a memory, we are not going to traverse through any of the
        # children. This is a simple pass-through between software and a
        # fixed memory block

        self.rtl_header.append(
            self.process_yaml(
                Memory.templ_dict['memory_adr_assignments'],
                {'path': self.path_underscored,
                 'bytes_w': int(self.get_regwidth() / 8),
                 'lower_bound': obj.absolute_address,
                 'upper_bound': obj.absolute_address + obj.total_size,
                 'addr_w': self.mementries.bit_length(),
                }
            )
        )

        if obj.get_property('sw') in (AccessType.rw, AccessType.r):
            self.rtl_header.append(
                self.process_yaml(
                    Memory.templ_dict['memory_rd_assignments'],
                    {'path': self.path_underscored,
                     'data_w': self.get_regwidth() - 1,
                    }
                )
            )

        if obj.get_property('sw') in (AccessType.rw, AccessType.w):
            self.rtl_header.append(
                self.process_yaml(
                    Memory.templ_dict['memory_wr_assignments'],
                    {'path': self.path_underscored,
                     'data_w': self.get_regwidth() - 1,
                    }
                )
            )

        # Assign variables that go to register bus multiplexer 
        self.__add_sw_mux_assignments()

        # We can/should only do this if there is no encapsulating 
        # regfile which create a generate
        self.__add_signal_instantiations()

        # Create comment and provide user information about register he/she
        # is looking at. Also add a description, if applicable
        self.rtl_header = [
            self.process_yaml(
                self.templ_dict['mem_comment'],
                {'inst_name': obj.inst_name,
                 'type_name': obj.type_name,
                 'memory_width': self.memwidth,
                 'memory_depth': self.mementries,
                 'dimensions': self.dimensions,
                 'depth': self.depth}
            ),
            self.get_description(),
            *self.rtl_header
            ]

    def __process_variables(self,
            obj: node.RegfileNode,
            parents_dimensions: list,
            parents_stride: list,
            glbl_settings: dict):

        self.mementries = obj.get_property('mementries')
        self.memwidth = obj.get_property('memwidth')
        self.addr_w = self.mementries.bit_length()

        if not math.log2(self.memwidth).is_integer():
            self.logger.fatal( "The defined memory width must be a power of 2. "\
                              f"it is now defined as '{self.memwidth}'")
            sys.exit(1)

        # Determine dimensions of register
        if obj.is_array:
            self.total_array_dimensions = [*parents_dimensions, *self.obj.array_dimensions]
            self.array_dimensions = self.obj.array_dimensions

            self.logger.warning("The memory is defined as array. The compiler not not "\
                                "provide any hooks to help here and expects that the user "\
                                "handles this outside of the memory block.")

            if self.obj.array_stride != int(self.mementries * self.memwidth / 8):
                self.logger.warning(f"The memory's stride ({self.obj.array_stride}) "\
                                    f"is unequal to the depth of the memory ({self.mementries} "\
                                    f"* {self.memwidth} / 8 = "\
                                    f"{int(self.mementries * self.memwidth / 8)}). This must be "\
                                     "kept in mind when hooking up the memory interface to an "\
                                     "external memory block.")
        else:
            self.total_array_dimensions = parents_dimensions
            self.array_dimensions = []
            self.total_stride = parents_stride

        self.total_dimensions = len(self.total_array_dimensions)
        self.depth = '[{}]'.format(']['.join(f"{i}" for i in self.array_dimensions))
        self.dimensions = len(self.array_dimensions)

    def __add_sw_mux_assignments(self):
        # Create list of mux-inputs to later be picked up by carrying addrmap
        self.sw_mux_assignment_var_name = \
            SWMuxEntry (
                data_wire = self.process_yaml(
                    Memory.templ_dict['sw_data_assignment_var_name'],
                    {'path': self.path_underscored,
                     'accesswidth': self.memwidth - 1}
                ),
                rdy_wire = self.process_yaml(
                    Memory.templ_dict['sw_rdy_assignment_var_name'],
                    {'path': self.path_underscored}
                ),
                err_wire = self.process_yaml(
                    Memory.templ_dict['sw_err_assignment_var_name'],
                    {'path': self.path_underscored}
                ),
                active_wire = f"{self.path_underscored}_mem_active"
            )

        if self.obj.get_property('sw') == AccessType.rw:
            access_type = 'sw_data_assignment_rw'
        elif self.obj.get_property('sw') == AccessType.r:
            access_type = 'sw_data_assignment_ro'
        else:
            access_type = 'sw_data_assignment_wo'

        self.rtl_footer = [
            self.process_yaml(
                self.templ_dict[access_type],
                {'path': self.path_underscored,
                 'sw_data_assignment_var_name': self.sw_mux_assignment_var_name.data_wire,
                 'sw_rdy_assignment_var_name': self.sw_mux_assignment_var_name.rdy_wire,
                 'sw_err_assignment_var_name': self.sw_mux_assignment_var_name.err_wire,
                }
            ),
            ''
        ]

    def create_mux_string(self):
        yield(
            SWMuxEntryDimensioned(
                mux_entry = self.sw_mux_assignment_var_name,
                dim = ''
            )
        )

    def get_regwidth(self) -> int:
        return self.memwidth

    def __add_signal_instantiations(self):
        # Add wire/register instantiations
        self.rtl_header = [
                '',
                *self.get_signal_instantiations_list(),
                *self.rtl_header
            ]

    def get_signal_instantiations_list(self):
        dict_list = [(key, value) for (key, value) in self.get_signals().items()]

        signal_width = min(max([len(value[0]) for (_, value) in dict_list]), 40)

        name_width = min(max([len(key) for (key, _) in dict_list]), 40)

        return [Memory.templ_dict['signal_declaration'].format(
                   name = key,
                   type = value[0],
                   signal_width = signal_width,
                   name_width = name_width,
                   unpacked_dim = '[{}]'.format(
                       ']['.join(
                           [str(y) for y in value[1]]))
                       if value[1] else '')
               for (key, value) in dict_list]
