#!/usr/bin/env python

__author__ = ('Imam Omar Mochtar')
__email__ = ('iomarmochtar@gmail.com',)
__version__ = "1.0"
__license__ = "GPL"

import os
import sys
import re
import logging
import traceback
from pprint import pprint
from mailmanclient import Client as Mailman3Client
from colorlog import ColoredFormatter
from six.moves.urllib_error import HTTPError
from ldap3 import Server, Connection, ALL, ALL_ATTRIBUTES, BASE
try:
    from ConfigParser import ConfigParser
except ImportError:
    # for python 3
    from configparser import ConfigParser


class M3Sync(object):

    __attrs = ['subscriber', 'owner', 'moderator']
    logger = logging.getLogger('Mailman3Sync')

    def __init__(self, config):

        self.sync = dict(config.items('sync'))
        self.config = config

        self.init_logger()
        self.init_hooks()
        self.init_mailman3api()
        self.init_ldap()

    def init_hooks(self):
        """
        Initialize hooks, for any module that will be executed after sync was done
        """
        conf = dict(self.config.items('hooks'))
        self.hooks = []
        for hook, module_name in conf.items():
            self.hooks.append({
                'name': hook,
                'module': getattr(__import__("hooks.{0}".format(module_name)), module_name),
                'conf': {} if not self.config.has_section(hook) else dict(self.config.items(hook))
            })

    def init_ldap(self):
        """
        Initialize ldap connection
        """
        conf = dict(self.config.items('ldap'))
        self.ldap = Connection(
            Server(conf['host'], get_info=ALL),
            conf['bind_dn'], conf['bind_pwd'], auto_bind=True
        )

    def init_mailman3api(self):
        """
        Initialize mailman3 API
        """
        # set conf api
        conf = dict(self.config.items('mailman3'))
        self.m3 = Mailman3Client(
            'http://{0}:{1}/3.1'.format(conf['host'], conf['port']),
            conf['user'], conf['pwd']
        )
        try:
            self.m3.system
        except Exception:
            msg = traceback.format_exc(limit=1)
            self.logger.error(
                "Error while connecting to conf api: {0}".format(msg))

    def init_logger(self):
        """
        Initiate log console & file (if enabled)
        """
        formatter = ColoredFormatter(
            "%(yellow)s%(asctime)s %(reset)s- %(log_color)s%(levelname)-8s%(reset)s - %(blue)s%(message)s",
            reset=True,
            log_colors={
                'DEBUG': 'cyan',
                'INFO':	 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'blue',
            }
        )

        log_lvl = logging.DEBUG

        handler = logging.StreamHandler()
        handler.setFormatter(formatter)

        self.logger.addHandler(handler)
        self.logger.setLevel(log_lvl)

        if 'log_file' in self.sync and self.sync['log_file']:
            fh = logging.FileHandler(self.sync['log_file'], 'a')
            fh.setLevel(log_lvl)
            fh.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(fh)

    def get_list_byname(self, domain, list_name):
        """
        a wrapper for get list by name
        """
        for mlist in domain.lists:
            if mlist.list_name != list_name:
                continue
            return mlist
        return None

    def get_list(self, name):
        """
        get list with additional prefix if enabled
        """
        prefix = self.sync['list_prefix']
        # lowercased
        name = name.lower()
        if not prefix:
            return name
        return "{0}{1}".format(prefix, name)

    def exec_hooks(self, ldap_data):
        """
        Running all available hooks
        """
        for hook in self.hooks:
            name = hook['name']
            self.logger.info("Executing hook {0}".format(name))
            result = hook['module'].main(
                conf=hook['conf'],
                instance=self,
                data=ldap_data
            )
            if result:
                self.logger.info(
                    "Result of hoook {0} is {1}".format(name, result))

    def main(self):
        # find group
        ret_attr = [
            self.sync['group_name_attr'], self.sync['subscriber_attr'], 
            self.sync['owner_attr'], self.sync['moderator_attr']
        ]
        search_result = self.ldap.search(
            self.sync['search_base'],
            self.sync['group_filter'],
            attributes=ret_attr
        )

        # regex was taken from http://emailregex.com/
        email_re = re.compile(
            r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)")

        ldap_data = {}
        for group in self.ldap.entries:
            # change all space to dot for group name
            list_name = re.sub(
                r'\s+', '.', getattr(group, self.sync['group_name_attr']).value)

            #
            ldap_data[self.get_list(list_name)] = dict(
                zip(self.__attrs, [[] for x in range(len(self.__attrs))])
            )

            for attr in self.__attrs:
                for dn in getattr(group, self.sync['{0}_attr'.format(attr)]):
                    # if it's not email form then search by it's DN. this is used if quering group member agains AD
                    email = None
                    if email_re.search(dn):
                        email = dn
                    else:
                        self.ldap.search(
                            dn,
                            self.sync['member_filter'],
                            attributes=[self.sync['mail_attr']],
                            search_scope=BASE
                        )
                        email = getattr(
                            self.ldap.entries[0], self.sync['mail_attr']).value

                    if not email:
                        self.logger.warning('LDAP data for {}, is not an email or it doesn\'t has email attribute'.format(dn))
                        continue

                    if 'replace_mail_domain' in self.sync and self.sync['replace_mail_domain']:
                        email = re.sub(r'@.*?$', '@{}'.format(self.sync['replace_mail_domain']), email)

                    # lower case the email
                    ldap_data[self.get_list(list_name)][attr].append(
                        email.lower())

        # make sure default domain exist
        self.logger.info('Creating default list domain: {0}'.format(
            self.sync['default_list_domain']))
        try:
            self.m3.create_domain(self.sync['default_list_domain'])
        except HTTPError:
            self.logger.warn('domain {0} already exist'.format(
                self.sync['default_list_domain']))

        domain = self.m3.get_domain(self.sync['default_list_domain'])

        # LDAP -> MAILMAN add data to mailman
        for list_name, datas in ldap_data.items():
            # Create List
            self.logger.info("Create list {0} in domain {1}".format(
                list_name, self.sync['default_list_domain']))
            try:
                mlist = domain.create_list(list_name)
                # disable welcome message
                mlist.settings['send_welcome_message'] = False
                mlist.settings.save()
            except HTTPError:
                self.logger.warn(
                    "List with name {0} already exists".format(list_name))
                mlist = self.get_list_byname(domain, list_name)

            mlist_name = mlist.fqdn_listname
            # subscriber
            for subscriber in datas['subscriber']:
                try:
                    self.logger.info("Add subscriber {0} to list {1}".format(
                        subscriber, mlist_name))
                    mlist.subscribe(subscriber, pre_verified=True,
                                    pre_confirmed=True, pre_approved=True)
                except HTTPError:
                    self.logger.warn("subscriber {0} already exist in {1}".format(
                        subscriber, mlist_name))

            # moderator
            for moderator in datas['moderator']:
                try:
                    self.logger.info(
                        "Add moderator {0} to list {1}".format(moderator, mlist_name))
                    mlist.add_moderator(moderator)
                except HTTPError:
                    self.logger.warn(
                        "moderator {0} already exist in {1}".format(moderator, mlist_name))

            # owner
            for owner in datas['owner']:
                try:
                    self.logger.info(
                        "Add owner {0} to list {1}".format(owner, mlist_name))
                    mlist.add_owner(owner)
                except HTTPError:
                    self.logger.warn(
                        "owner {0} already exist in {1}".format(moderator, mlist_name))

        # MAILMAN -> LDAP, check for diff then remove when it not exist
        # comparing member, if doesn't exist in ldap data then delete them
        for mlist in domain.lists:
            list_name = mlist.list_name
            # delete the rest of list if doesn't exist in ldap
            if list_name not in ldap_data.keys():

                if self.sync['delete_rest_list'] == 'true':

                    # some are excluded using regex pattern
                    if self.sync['exclude_list_re'] and re.search(r'{0}'.format(self.sync['exclude_list_re']), mlist.list_name):
                        continue

                    self.logger.info(
                        "Deleting list {0}".format(mlist.fqdn_listname))
                    mlist.delete()

                continue

            for member in mlist.members:
                if member.email not in ldap_data[list_name]['subscriber']:
                    self.logger.info("Unsubscribe {0} from list {1}".format(
                        member.email, list_name))
                    member.unsubscribe()

            for moderator in mlist.moderators:
                if moderator not in ldap_data[list_name]['moderator']:
                    self.logger.info(
                        "Removing moderator {0} from list {1}".format(moderator, list_name))
                    mlist.remove_moderator(moderator)

            for owner in mlist.owners:
                if owner not in ldap_data[list_name]['owner']:
                    self.logger.info(
                        "Removing owner {0} from list {1}".format(owner, list_name))
                    mlist.remove_owner(owner)

        self.exec_hooks(ldap_data)


if __name__ == "__main__":

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MAIN_CONF = os.path.join(BASE_DIR, 'config.ini')

    if not os.path.isfile(MAIN_CONF):
        logExit("main configuration not found")

    parser = ConfigParser()
    parser.read(MAIN_CONF)

    M3Sync(
        config=parser
    ).main()
