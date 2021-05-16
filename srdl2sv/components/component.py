import re
from itertools import chain
from typing import NamedTuple
from systemrdl import node

# Local modules
from log.log import create_logger

# Define NamedTuple
class Port(NamedTuple):
    name: str
    packed_dim: str
    unpacked_dim: list

class Component():
    def __init__(self):
        self.rtl_header = []
        self.rtl_footer = []
        self.children = []
        self.ports = dict()
        self.ports['input'] = []
        self.ports['output'] = []
        self.ports['inout'] = []

    def create_logger(self, name: str, config: dict):
        self.logger = create_logger(
            "{}".format(name),
            stream_log_level=config['stream_log_level'],
            file_log_level=config['file_log_level'],
            file_name=config['file_log_location'])
        self.logger.propagate = False

    def get_ports(self, port_type: str):
        self.logger.debug("Return port list")
        return [
            *self.ports[port_type],
            *list(chain(*[x.get_ports(port_type) for x in self.children]))
            ]

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
        new_path = re.match(r'(.*?)(\[.*\])?(.*)', path)
        return (''.join([new_path.group(1), new_path.group(3)]),
                new_path.group(2) if new_path.group(2) else '[0]')

    @staticmethod
    def get_ref_name(obj):
        name = []

        split_name = Component.split_dimensions(
            Component.get_underscored_path(
                obj.get_path(),
                obj.owning_addrmap.inst_name)
            )

        name.append(split_name[0])

        if isinstance(obj, (node.FieldNode)):
            name.append('_q')

        name.append(split_name[1])

        return ''.join(name)






