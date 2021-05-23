import re
from itertools import chain
from typing import NamedTuple
from systemrdl import node

# Local modules
from log.log import create_logger

# Define NamedTuple
class TypeDefMembers(NamedTuple):
    name: str
    member_type: str

class TypeDef(NamedTuple):
    name: str
    members: list[TypeDefMembers]

class Component():
    def __init__(self):
        self.rtl_header = []
        self.rtl_footer = []
        self.children = []
        self.ports = dict()
        self.signals = dict()
        self.ports['input'] = dict()
        self.ports['output'] = dict()
        self.field_type = ''

    def create_logger(self, name: str, config: dict):
        self.logger = create_logger(
            "{}".format(name),
            stream_log_level=config['stream_log_level'],
            file_log_level=config['file_log_level'],
            file_name=config['file_log_location'])
        self.logger.propagate = False

    def get_ports(self, port_type: str):
        self.logger.debug("Return port list")

        for x in self.children:
            self.ports[port_type] |= x.get_ports(port_type)

        return self.ports[port_type]

    def get_signals(self):
        self.logger.debug("Return signal list")

        for x in self.children:
            self.signals |= x.get_signals()

        return self.signals

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
            return Component.__add_tabs(
                        '\n'.join(rtl),
                        tab_width,
                        real_tabs)

        return '\n'.join(rtl)

    @staticmethod
    def __add_tabs(rtl: str, tab_width: int = 4, real_tabs = False) -> str:
        indent_lvl = 0

        # Define tab style
        tab = "\t" if real_tabs else " " 
        tab = tab_width * tab

        # Define triggers for which the indentation level will increment or
        # decrement on the next line
        incr_trigger = re.compile('\\bbegin\\b')
        decr_trigger = re.compile('\\bend\\b')

        rtl_indented = []

        # Go through RTL, line by line
        for line in rtl.split('\n', -1):
            skip_incr_check = False

            # Check if indentation must be decremented
            if decr_trigger.search(line):
                indent_lvl -= 1
                skip_incr_check = True

            # Add tabs
            rtl_indented.append("{}{}".format(tab*indent_lvl, line))

            # Check if tab level must be incremented
            if skip_incr_check:
                continue
            elif incr_trigger.search(line):
                indent_lvl += 1

        return '\n'.join(rtl_indented)

    @staticmethod
    def get_underscored_path(path: str, owning_addrmap: str):
        return path\
                .replace('[]', '')\
                .replace('{}.'.format(owning_addrmap), '')\
                .replace('.', '_')

    @staticmethod
    def split_dimensions(path: str):
        re_dimensions = re.compile('(\[[^]]\])')
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
                         self.array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            for x in yaml_obj['input_ports']:
                self.ports['input'][x['name'].format(path = self.path_underscored)] =\
                         (x['signal_type'].format(field_type = self.field_type),
                         self.array_dimensions)
        except (TypeError, KeyError):
            pass

        try:
            for x in yaml_obj['output_ports']:
                self.ports['output'][x['name'].format(path = self.path_underscored)] =\
                         (x['signal_type'].format(field_type = self.field_type),
                         self.array_dimensions)
        except (TypeError, KeyError):
            pass
