import importlib.resources as pkg_resources
import sys
import math
import yaml

from systemrdl import node
from systemrdl.rdltypes import AccessType

# Local packages
from srdl2sv.components.component import Component, SWMuxEntry, SWMuxEntryDimensioned
from srdl2sv.components import templates

class Memory(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'memory.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegfileNode,
            parents_dimensions: list,
            parents_strides: list,
            config: dict):
        super().__init__(
                    obj=obj,
                    config=config,
                    parents_strides=parents_strides,
                    parents_dimensions=parents_dimensions)

        # Save and/or process important variables
        self._init_variables()

        # Set object to 0 for easy addressing
        self.obj.current_idx = [0]

        # When in a memory, we are not going to traverse through any of the
        # children. This is a simple pass-through between software and a
        # fixed memory block

        self.rtl_header.append(
            self._process_yaml(
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
                self._process_yaml(
                    Memory.templ_dict['memory_rd_assignments'],
                    {'path': self.path_underscored,
                     'data_w': self.get_regwidth() - 1,
                    }
                )
            )

        if obj.get_property('sw') in (AccessType.rw, AccessType.w):
            self.rtl_header.append(
                self._process_yaml(
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
            self._process_yaml(
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

    def _init_variables(self):
        self.mementries = self.obj.get_property('mementries')
        self.memwidth = self.obj.get_property('memwidth')
        self.addr_w = self.mementries.bit_length()


    def sanity_checks(self):
        if not math.log2(self.memwidth).is_integer():
            self.logger.fatal("The defined memory width must be a power of 2. "\
                              "it is now defined as '%s'", self.memwidth)
            sys.exit(1)

        # Determine dimensions of register
        if self.obj.is_array:
            self.logger.warning("The memory is defined as array. The compiler not not "\
                                "provide any hooks to help here and expects that the user "\
                                "handles this outside of the memory block.")

            if self.obj.array_stride != int(self.mementries * self.memwidth / 8):
                self.logger.warning("The memory's stride (%i) is unequal to the depth "\
                                    "of the memory (%i * %i / 8 = %i). This must be "\
                                    "kept in mind when hooking up the memory interface "\
                                    "to an external memory block.",
                                    self.obj.array_stride,
                                    self.mementries,
                                    self.memwidth,
                                    int(self.mementries * self.memwidth / 8)
                                     )

    def __add_sw_mux_assignments(self):
        # Create list of mux-inputs to later be picked up by carrying addrmap
        self.sw_mux_assignment_var_name = \
            SWMuxEntry (
                data_wire = self._process_yaml(
                    Memory.templ_dict['sw_data_assignment_var_name'],
                    {'path': self.path_underscored,
                     'accesswidth': self.memwidth - 1}
                ),
                rdy_wire = self._process_yaml(
                    Memory.templ_dict['sw_rdy_assignment_var_name'],
                    {'path': self.path_underscored}
                ),
                err_wire = self._process_yaml(
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
            self._process_yaml(
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

    def __add_signal_instantiations(self):
        # Add wire/register instantiations
        self.rtl_header = [
                '',
                *self.get_signal_instantiations_list(),
                *self.rtl_header
            ]

    def get_signal_instantiations_list(self):
        dict_list = list(self.get_signals().items())
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

    def get_regwidth(self) -> int:
        return self.memwidth
