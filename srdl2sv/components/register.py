import importlib.resources as pkg_resources
import sys
from typing import Optional
import yaml

from systemrdl import node

# Local modules
from srdl2sv.components.component import Component, SWMuxEntry, SWMuxEntryDimensioned
from srdl2sv.components.field import Field
from srdl2sv.components import templates

class Register(Component):
    # Save YAML template as class variable
    templ_dict = yaml.load(
        pkg_resources.read_text(templates, 'register.yaml'),
        Loader=yaml.FullLoader)

    def __init__(
            self,
            obj: node.RegNode,
            config: dict,
            parents_dimensions: Optional[list],
            parents_strides: Optional[list],
            glbl_settings: dict):
        super().__init__(
                    obj=obj,
                    config=config,
                    parents_strides=parents_strides,
                    parents_dimensions=parents_dimensions)

        # Generate all variables that have anything to do with dimensions or strides
        self.__init_genvars()

        # Initialize all other variables
        self.__init_variables(glbl_settings)

        # Create RTL for fields of initial, non-alias register
        for field in self.obj.fields():
            # Use range to save field in an array. Reason is, names are allowed to
            # change when using an alias
            field_range = ':'.join(map(str, [field.msb, field.lsb]))

            self.children[field_range] = Field(field,
                                               self.total_array_dimensions,
                                               self.config)

            # Get properties from field that apply to whole register
            for key in self.properties:
                self.properties[key] |= self.children[field_range].properties[key]

            # Perform sanity check
            self.children[field_range].sanity_checks()

    def create_rtl(self):
        # Create RTL of children
        if self.config['external']:
            for child in self.children.values():
                child.create_external_rtl()
        else:
            for child in self.children.values():
                child.create_internal_rtl()

        # Create generate block for register and add comment
        if self.own_dimensions and not self.generate_active:
            self.rtl_header.append("generate")

        # Add N layers of for-loop starts
        for i in range(self.own_dimensions):
            self.rtl_header.append(
                Register.templ_dict['generate_for_start'].format(
                    iterator = ''.join(['gv_', chr(97+i+self.parents_depths)]),
                    limit = self.own_array_dimensions[i]))

        # Add decoders for all registers & aliases
        self.__add_address_decoder()

        # Fields will be added by get_rtl()

        # Add interrupt logic
        self.__add_interrupts()

        # Add assignment of read-wires
        self.__add_sw_mux_assignments()

        # Add N layers of for-loop end
        for i in range(self.own_dimensions-1, -1, -1):
            self.rtl_footer.append(
                Register.templ_dict['generate_for_end'].format(
                    dimension = ''.join(['gv_', chr(97+i)])))

        if self.own_dimensions and not self.generate_active:
            self.rtl_footer.append("\nendgenerate\n")

        # Add wire instantiation
        if not self.generate_active:
            # We can/should only do this if there is no encapsulating
            # regfile which create a generate
            self.__add_signal_instantiations()

        # Add description, if applicable
        self.rtl_header = [
                self.get_description(),
                *self.rtl_header
            ]

        # Create comment and provide user information about register he/she is looking at
        self.rtl_header = [
            Register.templ_dict['reg_comment'].format(
                name = self.obj.inst_name,
                dimensions = self.own_dimensions,
                depth = self.own_depth),
                *self.rtl_header
            ]

    def __add_interrupts(self):
        # Semantics on the intr and halt property:
        #   a) The intr and halt register properties are outputs; they should only
        #      occur on the right-hand side of an assignment in SystemRDL.
        #   b) The intr property shall always be present on a intr register even if
        #      no mask or enables are specified.
        #   c) The halt property shall only be present if haltmask or haltenable is
        #      specified on at least one field in the register.
        if self.properties['intr']:
            self.rtl_footer.append(Register.templ_dict['interrupt_comment']['rtl'])

            self.rtl_footer.append(
                self._process_yaml(
                    Register.templ_dict['interrupt_intr'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'list': ') || |('.join([
                         x.itr_masked for x in self.children.values() if x.itr_masked])
                    }
                )
            )

        if self.properties['halt']:
            self.rtl_footer.append(
                self._process_yaml(
                    Register.templ_dict['interrupt_halt'],
                    {'path': self.path_underscored,
                     'genvars': self.genvars_str,
                     'list': ') || |('.join([
                        x.itr_haltmasked for x in self.children.values() if x.itr_haltmasked])
                    }
                )
            )


    def __add_sw_mux_assignments(self):
        accesswidth = self.obj.get_property('accesswidth') - 1
        self.rtl_footer.append("")

        # Save name of main register
        main_reg_name = self.name_addr_mappings[0][0]

        for alias_idx, na_map in enumerate(self.name_addr_mappings):
            current_bit = 0

            # Handle fields
            list_of_fields = []
            bytes_read = set()
            bytes_written = set()

            for field in self.children.values():
                if na_map[0] in field.readable_by:
                    empty_bits = field.lsb - current_bit
                    current_bit = field.msb + 1

                    if empty_bits > 0:
                        list_of_fields.append(
                            f"{{{empty_bits}{{1'b{self.glbl_settings['rsvd_val']}}}}}")

                    list_of_fields.append(f"{field.path_underscored}_q{self.genvars_str}")

                    # Add to appropriate bytes
                    for byte in range(field.lsbyte, field.msbyte+1):
                        bytes_read.add(byte)

                if na_map[0] in field.writable_by:
                    # Add to appropriate bytes
                    for byte in range(field.lsbyte, field.msbyte+1):
                        bytes_written.add(byte)

            empty_bits = accesswidth - current_bit + 1

            no_reads = not list_of_fields

            if empty_bits > 0:
                list_of_fields.append(
                    f"{{{empty_bits}{{1'b{self.glbl_settings['rsvd_val']}}}}}")

            # Create list of mux-inputs to later be picked up by carrying addrmap
            self.sw_mux_assignment_var_name.append(
                SWMuxEntry(
                    data_wire = self._process_yaml(
                        Register.templ_dict['sw_data_assignment_var_name'],
                        {'path': na_map[0],
                         'accesswidth': accesswidth}
                    ),
                    rdy_wire = self._process_yaml(
                        Register.templ_dict['sw_rdy_assignment_var_name'],
                        {'path': na_map[0]}
                    ),
                    err_wire = self._process_yaml(
                        Register.templ_dict['sw_err_assignment_var_name'],
                        {'path': na_map[0]}
                    ),
                    active_wire = f"{na_map[0]}_active",
                )
            )

            # Return an error if *no* read or *no* write can be succesful.
            # If some bits cannot be read/write but others are succesful, don't return
            # an error.
            #
            # Furthermore, consider an error indication that is set for external registers
            if self.config['illegal_addresses']:
                wdgt_str = 'widget_if.byte_en'

                bytes_read_format = []
                bytes_read_sorted = sorted(bytes_read, reverse = True)

                try:
                    prev = msb = bytes_read_sorted[0]
                except IndexError:
                    # Do nothing. bytes_written simply didn't exist
                    # The loop below will simply not be entered
                    pass

                for i in bytes_read_sorted[0:]:
                    if prev - i > 1:
                        bytes_read_format.append(
                            f"|{wdgt_str}[{msb}:{prev}]" if msb > prev else f"{wdgt_str}[{msb}]")
                        msb = i

                    if i == bytes_read_sorted[-1]:
                        bytes_read_format.append(
                            f"|{wdgt_str}[{msb}:{i}]" if msb > i else f"{wdgt_str}[{msb}]")

                    prev = i

                bytes_written_format = []
                bytes_written_sorted = sorted(bytes_written, reverse = True)

                try:
                    prev = msb = bytes_written_sorted[0]
                except IndexError:
                    # Do nothing. bytes_written simply didn't exist
                    # The loop below will simply not be entered
                    pass

                for i in bytes_written_sorted[0:]:
                    if prev - i > 1:
                        bytes_written_format.append(
                            f"|{wdgt_str}[{msb}:{prev}]" if msb > prev else f"{wdgt_str}[{msb}]")
                        msb = i

                    if i == bytes_written_sorted[-1]:
                        bytes_written_format.append(
                            f"|{wdgt_str}[{msb}:{i}]" if msb > i else f"{wdgt_str}[{msb}]")

                    prev = i

                # Parse mux error-input
                sw_err_condition_vec = []
                sw_err_condition_vec.append(self._process_yaml(
                        Register.templ_dict['sw_err_condition'],
                        {'rd_byte_list_ored':
                            ' || '.join(bytes_read_format) if bytes_read else "1'b0",
                         'wr_byte_list_ored':
                            ' || '.join(bytes_written_format) if bytes_written else "1'b0"}
                    )
                )

                if self.config['external']:
                    if bytes_read:
                        for field in self.children.values():
                            if na_map[0] in field.readable_by:
                                sw_err_condition_vec.append(self._process_yaml(
                                        Register.templ_dict['external_err_condition'],
                                        {'path': '__'.join([main_reg_name, field.name]),
                                         'genvars': self.genvars_str,
                                         'rd_or_wr': 'r'}
                                    )
                                )

                    if bytes_written:
                        for field in self.children.values():
                            if na_map[0] in field.writable_by:
                                sw_err_condition_vec.append(self._process_yaml(
                                        Register.templ_dict['external_err_condition'],
                                        {'path': '__'.join([main_reg_name, field.name]),
                                         'genvars': self.genvars_str,
                                         'rd_or_wr': 'w'}
                                    )
                                )

                sw_err_condition = ' || '.join(sw_err_condition_vec)
            else:
                sw_err_condition = "1'b0"

            # If registers are implemented in RTL, they will be ready immediately. However,
            # if they are defined as 'external', there might be some delay
            if self.config['external']:
                if bytes_read:
                    sw_rdy_condition_vec = ['(']

                    for field in self.children.values():
                        sw_rdy_condition_vec.append(self._process_yaml(
                                Register.templ_dict['external_rdy_condition'],
                                {'path': '__'.join([main_reg_name, field.name]),
                                 'genvars': self.genvars_str,
                                 'rd_or_wr': 'r'}
                            )
                        )

                        sw_rdy_condition_vec.append(' && ')

                    sw_rdy_condition_vec.pop()
                    sw_rdy_condition_vec.append(' && widget_if.r_vld)')

                if bytes_read and bytes_written:
                    sw_rdy_condition_vec.append(' || ')

                if bytes_written:
                    sw_rdy_condition_vec.append('(')

                    for field in self.children.values():
                        sw_rdy_condition_vec.append(self._process_yaml(
                                Register.templ_dict['external_rdy_condition'],
                                {'path': '__'.join([main_reg_name, field.name]),
                                 'genvars': self.genvars_str,
                                 'rd_or_wr': 'w'}
                            )
                        )

                        sw_rdy_condition_vec.append(' && ')

                    sw_rdy_condition_vec.pop()
                    sw_rdy_condition_vec.append(' && widget_if.w_vld)')

                sw_rdy_condition = ''.join(sw_rdy_condition_vec)
            else:
                sw_rdy_condition = "1'b1"

            # Assign all values
            self.rtl_footer.append(
                self._process_yaml(
                    Register.templ_dict['sw_data_assignment'],
                    {'sw_data_assignment_var_name': self.sw_mux_assignment_var_name[-1].data_wire,
                     'sw_rdy_assignment_var_name': self.sw_mux_assignment_var_name[-1].rdy_wire,
                     'sw_err_assignment_var_name': self.sw_mux_assignment_var_name[-1].err_wire,
                     'genvars': self.genvars_str if not no_reads else '',
                     'rdy_condition': sw_rdy_condition,
                     'err_condition': sw_err_condition,
                     'alias_indicator': '(alias)' if alias_idx > 0 else '',
                     'list_of_fields': ', '.join(reversed(list_of_fields))}
                )
            )

    def create_mux_string(self):
        for mux_entry in self.sw_mux_assignment_var_name:
            # Loop through lowest dimension and add stride of higher
            # dimension once everything is processed
            if self.total_array_dimensions:
                vec = [0]*len(self.total_array_dimensions)

                for dimension in Register.__eval_genvars(vec, 0, self.total_array_dimensions):
                    yield (
                        SWMuxEntryDimensioned(
                            mux_entry = mux_entry,
                            dim = dimension
                        )
                    )
            else:
                yield (
                    SWMuxEntryDimensioned(
                        mux_entry = mux_entry,
                        dim = ''
                    )
                )

    @staticmethod
    def __eval_genvars(vec, depth, dimensions):
        for i in range(dimensions[depth]):
            vec[depth] = i

            if depth == len(dimensions) - 1:
                yield f"[{']['.join(map(str, vec))}]"
            else:
                yield from Register.__eval_genvars(vec, depth+1, dimensions)

        vec[depth] = 0

    def __add_address_decoder(self):
        if self.total_dimensions:
            access_wire_assign_field = 'access_wire_assign_multi_dim'
        else:
            access_wire_assign_field = 'access_wire_assign_1_dim'

        for i, name_addr_map in enumerate(self.name_addr_mappings):
            self.rtl_header.append(
                self._process_yaml(
                    Register.templ_dict['access_wire_comment'],
                    {'path': name_addr_map[0],
                     'alias': '(alias)' if i > 0 else '',
                    }
                )
            )

            self.rtl_header.append(
                self._process_yaml(
                    Register.templ_dict[access_wire_assign_field],
                    {'path': name_addr_map[0],
                     'addr': name_addr_map[1],
                     'genvars': self.genvars_str,
                     'genvars_sum': self.genvars_sum_str,
                     'depth': self.own_depth,
                    }
                )
            )

            # A wire that indicates a read is required
            if self.properties['sw_rd_wire']:
                # Check if a read is actually possible. Otherwise provide a wire
                # that is tied to 1'b0
                if self.properties['sw_rd']:
                    self.rtl_header.append(
                        self._process_yaml(
                            Register.templ_dict['read_wire_assign'],
                            {'path': name_addr_map[0],
                             'addr': name_addr_map[1],
                             'genvars': self.genvars_str,
                             'genvars_sum': self.genvars_sum_str,
                             'depth': self.own_depth,
                            }
                        )
                    )
                else:
                    self.rtl_header.append(
                        self._process_yaml(
                            Register.templ_dict['read_wire_assign_0'],
                            {'path': name_addr_map[0],
                             'genvars': self.genvars_str,
                            }
                        )
                    )

            # A wire that indicates a write is required
            if self.properties['sw_wr_wire']:
                # Check if a write is actually possible. Otherwise provide a wire
                # that is tied to 1'b0
                if self.properties['sw_wr']:
                    self.rtl_header.append(
                        self._process_yaml(
                            Register.templ_dict['write_wire_assign'],
                            {'path': name_addr_map[0],
                             'addr': name_addr_map[1],
                             'genvars': self.genvars_str,
                             'genvars_sum': self.genvars_sum_str,
                             'depth': self.own_depth,
                            }
                        )
                    )
                else:
                    self.rtl_header.append(
                        self._process_yaml(
                            Register.templ_dict['write_wire_assign_0'],
                            {'path': name_addr_map[0],
                             'genvars': self.genvars_str,
                            }
                        )
                    )

        # Add combined signal to be used for general access of the register
        if self.properties['swacc'] or self.properties['swmod']:
            self.rtl_header.append(
                self._process_yaml(
                    Register.templ_dict['w_wire_assign_any_alias'],
                    {'path': self.name_addr_mappings[0][0],
                     'genvars': self.genvars_str,
                     'sw_wrs_w_genvars': ' || '.join(
                         [''.join([x[0], '_sw_wr', self.genvars_str])
                             for x in self.name_addr_mappings])
                    }
                )
            )

        if self.properties['swacc']:
            self.rtl_header.append(
                self._process_yaml(
                    Register.templ_dict['r_wire_assign_any_alias'],
                    {'path': self.name_addr_mappings[0][0],
                     'genvars': self.genvars_str,
                     'sw_rds_w_genvars': ' || '.join(
                         [''.join([x[0], '_sw_rd', self.genvars_str])
                             for x in self.name_addr_mappings]),
                    }
                )
            )

    def __add_signal_instantiations(self):
        # Add wire/register instantiations
        self.rtl_header = [
                *self.get_signal_instantiations_list(),
                '',
                *self.rtl_header
            ]

    def get_signal_instantiations_list(self):
        dict_list = list(self.get_signals().items())
        signal_width = max(max([len(value.datatype) for (_, value) in dict_list]), 12)
        name_width = max([len(key) for (key, _) in dict_list])

        return [Register.templ_dict['signal_declaration'].format(
                   name = key,
                   type = value.datatype,
                   signal_width = signal_width,
                   name_width = name_width,
                   unpacked_dim = '[{}]'.format(
                       ']['.join(
                           [str(y) for y in value.dim]))
                       if value.dim else '')
               for (key, value) in dict_list]

    def add_alias(self, obj: node.RegNode):
        for field in obj.fields():
            # Use range to save field in an array. Reason is, names are allowed to
            # change when using an alias
            field_range = ':'.join(map(str, [field.msb, field.lsb]))

            try:
                self.children[field_range].add_sw_access(field, alias=True)
            except KeyError:
                self.logger.fatal(
                     "Range of field '%s' in alias register "
                     "'%s' does not correspond to range of field "
                     "in original register '%s'. This is illegal "
                     "according to 10.5.1 b) of the SystemRDL 2.0 LRM.",
                     field.inst_name,
                     obj.inst_name,
                     self.name)

                sys.exit(1)

        # Add name to list
        self.name_addr_mappings.append(
            (self.create_underscored_path_static(obj)[3], obj.absolute_address))

    def __init_variables(self, glbl_settings: dict):
        self.obj.current_idx = [0]

        # Save global settings
        self.glbl_settings = glbl_settings

        # Is this an external register?
        self.config['external'] = self.obj.external

        # Create mapping between (alias-) name and address
        self.name_addr_mappings = [
            (self.create_underscored_path_static(self.obj)[3], self.obj.absolute_address)
            ]

        # Geneate already started?
        self.generate_active = glbl_settings['generate_active']

        # Empty array for mux-input signals
        self.sw_mux_assignment_var_name = []

    def __init_genvars(self):
        super()._init_genvars()

        # Determine value to compare address with
        genvars_sum = []
        try:
            for i, stride in enumerate(self.total_stride):
                genvars_sum.append(''.join(['gv_', chr(97+i)]))
                genvars_sum.append("*")
                genvars_sum.append(str(stride))
                genvars_sum.append("+")

            genvars_sum.pop()

            self.logger.debug(
                "Multidimensional with dimensions '%s' and stride '%s'",
                self.total_array_dimensions, self.total_stride)

        except TypeError:
            self.logger.debug(
                "Caught expected TypeError because self.total_stride is empty")
        except IndexError:
            self.logger.debug(
                "Caugt expected IndexError because genvars_sum is empty")

        self.genvars_sum_str = ''.join(genvars_sum)

    def get_regwidth(self) -> int:
        return self.obj.get_property('regwidth')
