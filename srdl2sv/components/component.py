import re
from itertools import chain
from typing import NamedTuple
from systemrdl import node

# Local modules
from log.log import create_logger

# Define NamedTuple
class TypeDef(NamedTuple):
    scope: str
    width: int
    members: tuple

class Component():
    def __init__(self, obj, config):
        self.rtl_header = []
        self.rtl_footer = []
        self.children = []
        self.typedefs = dict()
        self.ports = dict()
        self.resets = set()
        self.signals = dict()
        self.ports['input'] = dict()
        self.ports['output'] = dict()
        self.field_type = ''

        # Save object
        self.obj = obj

        # Save name
        self.name = obj.inst_name

        # Create path
        self.create_underscored_path()

        # Save config
        self.config = config

        # Create logger object
        self.create_logger("{}.{}".format(self.owning_addrmap, self.path), config)
        self.logger.debug('Starting to process register "{}"'.format(obj.inst_name))

    def create_logger(self, name: str, config: dict):
        self.logger = create_logger(
            "{}".format(name),
            stream_log_level=config['stream_log_level'],
            file_log_level=config['file_log_level'],
            file_name=config['file_log_location'])
        self.logger.propagate = False

    def get_resets(self):
        self.logger.debug("Return reset list")

        for x in self.children:
            self.resets |= x.get_resets()

        return self.resets

    def get_ports(self, port_type: str):
        self.logger.debug("Return port list")

        for x in self.children:
            self.ports[port_type] |= x.get_ports(port_type)

        return self.ports[port_type]

    def get_max_dim_depth(self) -> int:
        try:
            total_dimensions = self.total_dimensions
            total_array_dimensions = self.total_array_dimensions
        except AttributeError:
            total_dimensions = 0
            total_array_dimensions = []

        self.logger.debug("Return depth '{}' for dimensions (including "\
                          "parents) '{}'".format(total_dimensions, total_array_dimensions))
        return max([
            total_dimensions,
            *[x.get_max_dim_depth() for x in self.children]
            ])

    def get_signals(self):
        self.logger.debug("Return signal list")

        for x in self.children:
            self.signals |= x.get_signals()

        return self.signals

    def get_typedefs(self):
        self.logger.debug("Return typedef list")

        for x in self.children:
            self.typedefs |= x.get_typedefs()

        return self.typedefs

    def get_rtl(self, tab_width: int = 0, real_tabs: bool = False) -> str:
        self.logger.debug("Return RTL")

        # Loop through children and append RTL
        rtl_children = []

        for child in self.children:
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
        trigger_re = re.compile(r'.*?((?:\bbegin\b|\{)|(?:\bend\b|}))([^$]*)')

        rtl_indented = []

        # Go through RTL, line by line
        for line in rtl.split('\n', -1):
            skip_incr_check = False

            line_split = line

            # This is done because the increment of the indent level must
            # be delayed one cycle
            indent_lvl = indent_lvl_next

            while 1:
                # Check if indentation must be decremented
                matchObj = trigger_re.match(line_split)

                if matchObj:
                    if matchObj.group(1) in ('begin', '{'):
                        indent_lvl_next += 1
                    else:
                        indent_lvl = indent_lvl_next - 1
                        indent_lvl_next -= 1

                    line_split = matchObj.group(2)

                    if not line_split:
                        break
                else:
                    break

            # Add tabs
            rtl_indented.append("{}{}".format(tab*indent_lvl, line))


        return '\n'.join(rtl_indented)

    @staticmethod
    def get_underscored_path(path: str, owning_addrmap: str):
        return path\
                .replace('[]', '')\
                .replace('{}.'.format(owning_addrmap), '')\
                .replace('.', '_')

    @staticmethod
    def split_dimensions(path: str):
        re_dimensions = re.compile('(\[[^]]*\])')
        new_path = re_dimensions.sub('', path)
        return (new_path, ''.join(re_dimensions.findall(path)))

    @staticmethod
    def get_signal_name(obj):
        name = []

        try:
            child_obj = obj.node
        except AttributeError:
            child_obj = obj

        split_name = Component.split_dimensions(
            Component.get_underscored_path(
                child_obj.get_path(),
                child_obj.owning_addrmap.inst_name)
            )

        name.append(split_name[0])

        if isinstance(obj, node.FieldNode):
            name.append('_q')
        elif isinstance(obj, node.SignalNode):
            pass
        else:
            name.append('_')
            name.append(obj.name)

        name.append(split_name[1])

        return ''.join(name)

    def yaml_signals_to_list(self, yaml_obj):
        try:
            for x in yaml_obj['signals']:
                self.signals[x['name'].format(path = self.path_underscored)] =\
                         (x['signal_type'].format(field_type = self.field_type),
                         self.total_array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            for x in yaml_obj['input_ports']:
                self.ports['input'][x['name'].format(path = self.path_underscored)] =\
                         (x['signal_type'].format(field_type = self.field_type),
                         self.total_array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            for x in yaml_obj['output_ports']:
                self.ports['output'][x['name'].format(path = self.path_underscored)] =\
                         (x['signal_type'].format(field_type = self.field_type),
                         self.total_array_dimensions)
        except (TypeError, KeyError):
            pass

    @staticmethod
    def process_reset_signal(reset_signal):
        rst = dict()

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
        except:
            rst['async'] = False
            rst['name'] = None
            rst['edge'] = None
            rst['value'] = "'x"
            rst['active'] = "-"
            rst['type'] = "-"

        return rst

    def create_underscored_path(self):
        self.owning_addrmap = self.obj.owning_addrmap.inst_name
        self.full_path = Component.split_dimensions(self.obj.get_path())[0]
        self.path = self.full_path\
                        .replace('{}.'.format(self.owning_addrmap), '')

        self.path_underscored = self.path.replace('.', '__')
