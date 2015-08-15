# Copyright 2015 Abhijit Menon-Sen <ams@2ndQuadrant.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

#############################################
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ast
import shlex
import re

from ansible import constants as C
from ansible.errors import *
from ansible.inventory.host import Host
from ansible.inventory.group import Group
from ansible.inventory.expand_hosts import detect_range
from ansible.inventory.expand_hosts import expand_hostname_range
from ansible.utils.unicode import to_unicode

class InventoryParser(object):
    """
    Ansible INI-format inventory parser
    """

    def __init__(self, filename=C.DEFAULT_HOST_LIST):
        self.filename = filename

        # Start with an empty host list and the default 'all' and
        # 'ungrouped' groups.

        self.hosts = {}
        self.patterns = {}
        self.groups = dict(
            all = Group(name='all'),
            ungrouped = Group(name='ungrouped')
        )

        # Read in the hosts, groups, and variables defined in the
        # inventory file.

        with open(filename) as fh:
            self.lines = fh.readlines()
            self._parse()

        # Finally, add all top-level groups (including 'ungrouped') as
        # children of 'all'.

        for group in self.groups.values():
            if group.depth == 0 and group.name != 'all':
                self.groups['all'].add_child_group(group)

    def _parse(self):
        pending_declaration = {}

        self._compile_patterns()

        # We pretend that the first line is '[ungrouped]' and that we expect to
        # find host definitions. Then we make a single pass through each line of
        # the inventory, building up self.groups and adding hosts, subgroups,
        # and setting variables as we go.

        section = 'ungrouped'
        state = ''

        i = 0
        for line in self.lines:
            i += 1

            # Skip empty lines and comments
            if line == '\n' or line.startswith(";") or line.startswith("#"):
                continue

            # Is this a section header? That tells us what group we're parsing
            # definitions for, and what kind of definitions to expect.

            m = self.patterns['section'].match(line)
            if m:
                (section, state) = m.groups()

                # If we haven't seen this section before, we add a new Group.
                #
                # Either [groupname] or [groupname:children] is sufficient to
                # declare a group, but [groupname:vars] is allowed only if the
                # group is declared elsewhere (not necessarily earlier). We add
                # the group anyway, but make a note in pending_declaration and
                # check at the end.

                if section not in self.groups:
                    self.groups[section] = Group(name=section)

                    if state == 'vars':
                        pending_declaration[section] = dict(
                            line=i, state=state, name=section
                        )
                    elif section in pending_declaration:
                        del pending_declaration[section]

                continue

            # It's not a section, so the current state tells us what kind of
            # definition it must be. The individual parsers will raise an
            # error if we feed them something they can't digest.

            # [groupname] contains host definitions that must be added to
            # the current group.
            if state == '':
                hosts = self._parse_host_definition(line, i)
                for h in hosts:
                    self.groups[section].add_host(h)

            # [groupname:vars] contains variable definitions that must be
            # applied to the current group.
            elif state == 'vars':
                (k, v) = self._parse_variable_definition(line, i)
                self.groups[section].set_variable(k, v)

            # [groupname:children] contains subgroup names that must be
            # added as children of the current group. The subgroup names
            # must themselves be declared as groups, but as before, they
            # may only be declared later.
            elif state == 'children':
                child = self._parse_group_name(line, i)

                if child not in self.groups:
                    self.groups[child] = Group(name=child)
                    pending_declaration[child] = dict(
                        line=i, state=state,
                        name=child, parent=section
                    )

                self.groups[section].add_child_group(self.groups[child])

            # Sorry, we don't know what this line is.
            else:
                expected = state or 'host'
                raise AnsibleError("%s:%d: Expected comment, section, or %s definition, got: %s" % (self.filename, i, expected, line))

        # Any entries in pending_declaration not removed by a group declaration
        # above mean that there was an unresolved forward reference. We report
        # only the first such error here.

        for g in pending_declaration:
            if g.state == 'vars':
                raise AnsibleError("%s:%d: Can't define variables for undefined group %s" % (self.filename, g.line, g.name))
            elif g.state == 'children':
                raise AnsibleError("%s:%d: Can't include undefined group %s in group %s" % (self.filename, g.line, g.name, g.parent))

    def _parse_group_name(self, line, i):
        '''
        Takes a single line and tries to parse it as a group name. Returns the
        group name if successful, or raises an error.
        '''

        m = self.patterns['groupname'].match(line)
        if m:
            return m.group(0)

        raise AnsibleError("%s:%d: Expected group name, got: %s" % (self.filename, i, line))

    def _parse_host_definition(self, line, i):
        '''
        Takes a single line and tries to parse it as a host definition. Returns
        a list of Hosts if successful, or raises an error.
        '''

        # XXX Not yet finished.

        raise AnsibleError("%s:%d: Expected host definition, got: %s" % (self.filename, i, line))

    def _parse_variable_definition(self, line):
        '''
        Takes a string and tries to parse it as a variable definition. Returns
        the key and value if successful, or raises an error.
        '''

        # TODO: We parse variable assignments as a key (anything to the left of
        # an '='"), an '=', and a value (anything left) and leave the value to
        # _parse_value to sort out. We should be more systematic here about
        # defining what is acceptable, how quotes work, and so on.

        if '=' in line:
            (k, v) = [e.strip() for e in line.split("=", 1)]
            return (k, self._parse_value(v))

        raise AnsibleError("%s:%d: Expected key=value, got: %s" % (self.filename, i, line))

    @staticmethod
    def _parse_value(v):
        if "#" not in v:
            try:
                v = ast.literal_eval(v)
            # Using explicit exceptions.
            # Likely a string that literal_eval does not like. We wil then just set it.
            except ValueError:
                # For some reason this was thought to be malformed.
                pass
            except SyntaxError:
                # Is this a hash with an equals at the end?
                pass
        return to_unicode(v, nonstring='passthru', errors='strict')

    def get_host_variables(self, host):
        return {}

    def _compile_patterns(self):
        '''
        Compiles the regular expressions required to parse the inventory and
        stores them in self.patterns.
        '''

        # TODO: What are the real restrictions on group names, or rather, what
        # should they be? At the moment, they must be non-empty sequences of non
        # whitespace characters excluding ':' and ']'.

        self.patterns['groupname'] = re.compile('^([^:\]\s]+)')

        # Section names are square-bracketed expressions at the beginning of a
        # line, comprising (1) a group name optionally followed by (2) a tag
        # that specifies the contents of the section. We ignore any trailing
        # whitespace and/or the beginning of a comment.

        self.patterns['section'] = re.compile(
            r'''^\[
                    ([^:\]\s]+)             # group name
                    (?::(vars|children))?   # optional : and tag name
                \]
                \s*#*                       # ignore trailing comments
            ''', re.X
        )
