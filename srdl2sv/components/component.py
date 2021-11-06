import re
import math
import sys
from typing import NamedTuple, Optional
from dataclasses import dataclass

from systemrdl import node

# Local modules
from srdl2sv.log.log import create_logger

# Define NamedTuple
class TypeDef(NamedTuple):
    scope: str
    width: int
    members: tuple

@dataclass
class SWMuxEntry:
    data_wire: str
    rdy_wire: str
    err_wire: str
    active_wire: str

@dataclass
class SWMuxEntryDimensioned():
    mux_entry: SWMuxEntry
    dim: str

class Component():
    def __init__(
            self,
            obj,
            config,
            parents_dimensions: Optional[list] = None,
            parents_strides: Optional[list] = None):

        self.rtl_header = []
        self.rtl_footer = []
        self.children = {}
        self.typedefs = {}
        self.ports = {}
        self.resets = set()
        self.signals = {}
        self.ports['input'] = {}
        self.ports['output'] = {}
        self.field_type = ''

        # Save object
        # TODO: should probably be list because of alias registers
        self.obj = obj

        # Save name
        self.name = obj.inst_name

        # Create path
        self.create_underscored_path()

        # Save config
        self.config = config.copy()

        # Generate all variables that have anything to do with dimensions or strides
        self.__init_dimensions(parents_dimensions)
        self.__init_strides(parents_strides)

        # Save and/or process important variables
        self.__init_variables()

        # Create logger object
        self.__create_logger(self.full_path, config)
        self.logger.debug(f"Starting to process {self.__class__.__name__} '{obj.inst_name}'")

    def __init_variables(self):
        # By default, registers and fields are not interrupt registers
        self.properties = {
            'intr': False,
            'halt': False,
            'swmod': False,
            'swacc': False,
            'sw_rd': False,
            'sw_wr': False,
            'sw_rd_wire': False,
            'sw_wr_wire': False,
        }

        self.genvars_str = ''


    def __create_logger(self, name: str, config: dict):
        self.logger = create_logger(
            name,
            stdout_log_level=config['stdout_log_level'],
            file_log_level=config['file_log_level'],
            file_name=config['file_log_location'])
        self.logger.propagate = False

    def __init_dimensions(self, parents_dimensions):
        # Determine dimensions of register
        self.sel_arr = 'single'
        self.total_array_dimensions = parents_dimensions if parents_dimensions else []
        self.own_array_dimensions = []

        try:
            if self.obj.is_array:
                self.sel_arr = 'array'
                self.total_array_dimensions = [*self.total_array_dimensions,
                                               *self.obj.array_dimensions]
                self.own_array_dimensions = self.obj.array_dimensions
        except AttributeError:
            pass

        # How many dimensions were already part of some higher up hierarchy?
        self.parents_depths = len(parents_dimensions) if parents_dimensions else 0

        # Calculate depth and number of dimensions
        self.own_depth = '[{}]'.format(']['.join(f"{i}" for i in self.own_array_dimensions))
        self.own_dimensions = len(self.own_array_dimensions)
        self.total_dimensions = len(self.total_array_dimensions)

    def __init_strides(self, parents_strides):
        self.total_stride = parents_strides if parents_strides else []

        try:
            if self.obj.is_array:
                # Merge parent's stride with stride of this regfile. Before doing so, the
                # respective stride of the different dimensions shall be calculated
                self.total_stride = [
                    *self.total_stride,
                    *[math.prod(self.own_array_dimensions[i+1:])
                        *self.obj.array_stride
                            for i, _ in enumerate(self.own_array_dimensions)]
                    ]
        except AttributeError:
            # Not all Nodes can be an array. In that case, just take the parent's stride
            pass

    def _init_genvars(self):
        # Calculate how many genvars shall be added
        genvars = [f"[gv_{chr(97+i)}]" for i in range(self.total_dimensions)]
        self.genvars_str = ''.join(genvars)

    def get_resets(self):
        self.logger.debug("Return reset list")

        for child in self.children.values():
            self.resets |= child.get_resets()

        return self.resets

    def get_ports(self, port_type: str):
        self.logger.debug("Return port list")

        for child in self.children.values():
            self.ports[port_type] |= child.get_ports(port_type)

        return self.ports[port_type]

    def get_max_dim_depth(self) -> int:
        self.logger.debug(f"Return depth '{self.total_dimensions}' for dimensions (including "\
                          f"parents) '{self.total_array_dimensions}'")

        return max([
            self.total_dimensions,
            *[x.get_max_dim_depth() for x in self.children.values()]
            ])

    def get_signals(self, no_children = False):
        self.logger.debug("Return signal list")

        if not no_children:
            for child in self.children.values():
                self.signals |= child.get_signals()

        return self.signals

    def get_typedefs(self):
        self.logger.debug("Return typedef list")

        for child in self.children.values():
            self.typedefs |= child.get_typedefs()

        return self.typedefs

    def get_rtl(self, tab_width: int = 0, real_tabs: bool = False) -> str:
        self.logger.debug("Return RTL")

        # Loop through children and append RTL
        rtl_children = []

        for child in self.children.values():
            rtl_children.append(child.get_rtl())

        # Concatenate header, main, and footer
        rtl = [*self.rtl_header, *rtl_children, *self.rtl_footer]

        # Join lists and return string
        if tab_width > 0:
            return Component.add_tabs(
                        '\n'.join(rtl),
                        tab_width,
                        real_tabs)

        return '\n'.join(rtl)

    @staticmethod
    def add_tabs(rtl: str, tab_width: int = 4, real_tabs = False) -> str:
        indent_lvl = 0
        indent_lvl_next = 0

        # Define tab style
        tab = "\t" if real_tabs else " "
        tab = tab_width * tab

        # Define triggers for which the indentation level will increment or
        # decrement on the next line
        trigger_re = re.compile(r"""
            .*?(?P<keyword>
                (?:\bbegin\b|\{|\bcase\b|<<INDENT>>)|
                (?:\bend\b|}|\bendcase\b|<<UNINDENT>>)
            )(?P<remainder>[^$]*)
            """, flags=re.VERBOSE)

        rtl_indented = []

        # Go through RTL, line by line
        for line in rtl.split('\n', -1):
            line_split = line

            # This is done because the increment of the indent level must
            # be delayed one cycle
            indent_lvl = indent_lvl_next

            while 1:
                # Check if indentation must be decremented
                if match_obj := trigger_re.match(line_split):
                    if match_obj.group('keyword') in ('begin', '{', 'case', '<<INDENT>>'):
                        indent_lvl_next += 1
                    else:
                        indent_lvl = indent_lvl_next - 1
                        indent_lvl_next -= 1

                    line_split = match_obj.group('remainder')

                    if not line_split:
                        break
                else:
                    break

            # Add tabs
            if line.strip() not in ("<<INDENT>>", "<<UNINDENT>>", "<<SQUASH_NEWLINE>>"):
                rtl_indented.append(f"{tab*indent_lvl}{line}")

        return '\n'.join(rtl_indented)

    @staticmethod
    def __get_underscored_path(path: str, owning_addrmap: str):
        return path\
                .replace('[]', '')\
                .replace(f"{owning_addrmap}.", '')\
                .replace('.', '__')

    @staticmethod
    def __split_dimensions(path: str):
        re_dimensions = re.compile(r'(\[[^]]*\])')
        new_path = re_dimensions.sub('', path)
        return (new_path, ''.join(re_dimensions.findall(path)))

    def get_signal_name(self, obj):
        name = []

        try:
            child_obj = obj.node
        except AttributeError:
            child_obj = obj

        split_name = self.__split_dimensions(
            self.__get_underscored_path(
                child_obj.get_path(),
                child_obj.owning_addrmap.inst_name)
            )

        name.append(split_name[0])

        if isinstance(obj, node.FieldNode):
            name.append('_q')
        elif isinstance(obj, node.SignalNode):
            # Must add it to signal list
            self.ports['input'][obj.inst_name] =\
                ("logic" if obj.width == 1 else f"logic [{obj.width}:0]", [])
        else:
            name.append('_')
            name.append(obj.name)

            # This is a property. Check if the original field actually has this property
            if obj.name in ("intr", "halt"):
                pass
            elif not obj.node.get_property(obj.name):
                self.logger.fatal(f"Reference to the property '{obj.name}' of instance "
                                  f"'{obj.node.get_path()}' found. This instance does "
                                   "hold the reference property! Please fix this if you "
                                   "want me to do my job properly.")

                sys.exit(1)

        name.append(split_name[1])

        return ''.join(name)

    def _process_yaml(self,
                     yaml_obj,
                     values: dict = {},
                     skip_signals: bool = False,
                     skip_inputs: bool = False,
                     skip_outputs: bool = False):
        try:
            if skip_signals:
                raise KeyError

            for signal in yaml_obj['signals']:
                try:
                    array_dimensions = [] if signal['no_unpacked'] \
                                                else self.total_array_dimensions
                except KeyError:
                    array_dimensions = self.total_array_dimensions

                self.signals[signal['name'].format(**values)] =\
                         (signal['signal_type'].format(**values),
                         array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            if skip_inputs:
                raise KeyError

            for input_p in yaml_obj['input_ports']:
                try:
                    array_dimensions = [] if input_p['no_unpacked'] \
                                                else self.total_array_dimensions
                except KeyError:
                    array_dimensions = self.total_array_dimensions

                self.ports['input'][input_p['name'].format(**values)] =\
                         (input_p['signal_type'].format(**values),
                         array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            if skip_outputs:
                raise KeyError

            for output_p in yaml_obj['output_ports']:
                try:
                    array_dimensions = [] if output_p['no_unpacked'] \
                                                else self.total_array_dimensions
                except KeyError:
                    array_dimensions = self.total_array_dimensions

                self.ports['output'][output_p['name'].format(**values)] =\
                         (output_p['signal_type'].format(**values),
                         array_dimensions)
        except (TypeError, KeyError):
            pass

        # Return RTL with values
        return yaml_obj['rtl'].format(**values)

    def create_underscored_path(self):
        self.owning_addrmap, self.full_path, self.path, self.path_underscored =\
            Component.create_underscored_path_static(self.obj)

    @staticmethod
    def create_underscored_path_static(obj):
        owning_addrmap = obj.owning_addrmap.inst_name
        full_path = Component.__split_dimensions(obj.get_path())[0]
        path = full_path.replace(f"{owning_addrmap}.", '')

        path_underscored = path.replace('.', '__')

        return (owning_addrmap, full_path, path, path_underscored)

    def get_description(self):
        if self.config['descriptions'][self.__class__.__name__]:
            if desc := self.obj.get_property('desc'):
                return self._process_yaml(
                        self.templ_dict['description'],
                        {'desc': desc},
                )

        return ''

    def get_regwidth(self) -> int:
        return self.regwidth
