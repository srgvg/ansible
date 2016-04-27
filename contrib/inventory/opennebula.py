#!/usr/bin/env python
# Copyright 2016 Serge van Ginderachter <serge@vanginderachter.be>
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

'''
Opennebula external inventory script
=================================

Generates inventory that Ansible can understand by making API requests

When run against a specific host, this script returns the following variables

When run in --list mode, instances are grouped by the following categories:
 - zone:
   zone group name examples are us-central1-b, europe-west1-a, etc.
 - instance tags:
   An entry is created for each tag.  For example, if you have two instances
   with a common tag called 'foo', they will both be grouped together under
   the 'tag_foo' name.
 - network name:
   the name of the network is appended to 'network_' (e.g. the 'default'
   network will result in a group named 'network_default')
 - machine type
   types follow a pattern like n1-standard-4, g1-small, etc.
 - running status:
   group name prefixed with 'status_' (e.g. status_running, status_stopped,..)
 - image:
   when using an ephemeral/scratch disk, this will be set to the image name
   used when creating the instance (e.g. debian-7-wheezy-v20130816).  when
   your instance was created with a root persistent disk it will be set to
   'persistent_disk' since there is no current way to determine the image.

Examples:
  Execute uname on all instances in the us-central1-a zone
  $ ansible -i gce.py us-central1-a -m shell -a "/bin/uname -a"

  Use the GCE inventory script to print out instance specific information
  $ contrib/inventory/gce.py --host my_instance

Version: 0.1.0
Author: Serge van Ginderachter <serge@vanginderachter.be>
        based on the gce.py by Eric Johnson <erjohnso@google.com>
'''

USER_AGENT_PRODUCT = "Ansible-opennebula_inventory_plugin"
USER_AGENT_VERSION = "v1"

import os
import sys
import argparse
import ConfigParser
import xmlrpclib
import lxml.etree as etree

try:
    import json
except ImportError:
    import simplejson as json

import xmltodict


class OpennebulaInventory(object):

    def __init__(self):
        # Read settings and parse CLI arguments
        self.parse_cli_args()
        self.parse_config()

        ## Just display data for specific host
        #if self.args.host:
        #    data = dict()
        ## Otherwise, assume user wants all instances grouped
        #elif self.args.list:
        #    data = dict()

        self.run()


    def parse_config(self):

        self.config = ConfigParser.SafeConfigParser()
        config_files =  [os.path.abspath(sys.argv[0]).rstrip('.py') + '.ini', 'opennebula.ini']
        for config_file in config_files:
            if os.path.exists(config_file):
                self.config.read(config_file)
                break

        self.server = self.config.get('one', 'server')
        user = self.config.get('one', 'user')
        password = self.config.get('one', 'password')
        self.one_auth = '{0}:{1}'.format(user, password)


    def output(self, data):
        print self.json_format_dict(data, pretty=self.args.pretty)


    def parse_cli_args(self):
        ''' Command line argument processing '''

        parser = argparse.ArgumentParser(
            description='Produce an Ansible Inventory json for Opennebula')
        parser.add_argument('--list', action='store_true', default=True,
                            help='List instances (default: True)')
        parser.add_argument('--host', action='store',
                            help='Get all information about an instance')
        parser.add_argument('--pretty', action='store_true', default=False,
                            help='Pretty format (default: False)')
        self.args = parser.parse_args()


    def json_format_dict(self, data, pretty=False):
        ''' Converts a dict to a JSON object and dumps it as a formatted
        string '''

        if pretty:
            return json.dumps(data, sort_keys=True, indent=2)
        else:
            return json.dumps(data)


    def get_proxy(self):
        return xmlrpclib.ServerProxy(self.server)


    def get_vm_list(self):
        # http://docs.opennebula.org/4.12/integration/system_interfaces/api.html#one-vmpool-info
        response = self.get_proxy().one.vmpool.info(self.one_auth, -2, -1, -1, 3) #-2)
        if response[0]:
            xml = response[1]
        else:
            raise Exception(response[1])
        return xmltodict.parse(xml)["VM_POOL"]["VM"]


    def ansiventory_add_host(self, hostname, hostvars, groupname):
        if not groupname in self.ansiventory:
            self.ansiventory[groupname] = []
        if not hostname in self.ansiventory[groupname]:
            self.ansiventory[groupname].append(hostname)
        self.ansiventory["_meta"][hostname] = hostvars

    def make_ansible_inventory(self):
        self.ansiventory = { "_meta": {"hostvars": {}}}
        for onevm in self.one_vm_list:
            hostname = onevm["NAME"]
            hostname = onevm["TEMPLATE"]["CONTEXT"]["ETH0_IP"]
            groupname = onevm["GNAME"]
            hostvars = onevm
            self.ansiventory_add_host(hostname, hostvars, groupname)

    def run(self):
        self.one_vm_list = self.get_vm_list()
        self.make_ansible_inventory()
        self.output(self.ansiventory)

if __name__ == '__main__':
    # Run the script
    OpennebulaInventory()
    sys.exit(0)
