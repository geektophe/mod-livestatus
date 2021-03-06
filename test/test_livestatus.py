#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2009-2010:
#    Gabes Jean, naparuba@gmail.com
#    Gerhard Lausser, Gerhard.Lausser@consol.de
#
# This file is part of Shinken.
#
# Shinken is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shinken is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Shinken.  If not, see <http://www.gnu.org/licenses/>.


#
# This file is used to test host- and service-downtimes.
#


import os
import re
import sys
import time
import random

from shinken_test import unittest

from shinken.brok import Brok
from shinken.objects.timeperiod import Timeperiod
from shinken.comment import Comment
from shinken.util import from_bool_to_int
from shinken.schedulerlink import SchedulerLink
from shinken.reactionnerlink import ReactionnerLink
from shinken.pollerlink import PollerLink
from shinken.brokerlink import BrokerLink

from shinken_modules import TestConfig
from shinken_modules import LiveStatusClientThread

from mock_livestatus import mock_livestatus_handle_request


sys.setcheckinterval(10000)

class LiveStatusTest(TestConfig):
    def setUp(self):
        self.setup_with_file('etc/shinken_1r_1h_1s.cfg')
        if hasattr(Comment, "_id"):
            Comment._id = 1
        else:
            Comment.id = 1
        self.testid = str(os.getpid() + random.randint(1, 1000))
        self.init_livestatus()
        print "Cleaning old broks?"
        self.sched.conf.skip_initial_broks = False
        self.sched.brokers['Default-Broker'] = {'broks' : {}, 'has_full_broks' : False}
        self.sched.fill_initial_broks('Default-Broker')
        self.update_broker()
        self.livestatus_path = None
        self.nagios_config = None
        # add use_aggressive_host_checking so we can mix exit codes 1 and 2
        # but still get DOWN state
        host = self.sched.hosts.find_by_name("test_host_0")
        host.__class__.use_aggressive_host_checking = 1


@mock_livestatus_handle_request
class TestConfigSmall(LiveStatusTest):

    def test_get_request_encoding(self):
        self.print_header()
        lqt = LiveStatusClientThread(None, None, self.livestatus_broker)
        lqt.buffer_list = [b'testééé\n\n']
        output = lqt.get_request()
        self.assertEqual(b"testééé\n\n", output)

    def test_check_type(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 2, 'CRIT'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")

        request = """GET services
Columns: host_name service_description state check_type
Filter: host_name = test_host_0
Filter: description = test_ok_0
OutputFormat: csv
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        # The last check was an active check -> check_type=0
        goodresponse = """test_host_0;test_ok_0;2;0
"""
        print response
        self.assertEqual(goodresponse, response )

        excmd = '[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_0;1;WARN' % int(time.time())
        self.sched.run_external_command(excmd)
        self.scheduler_loop(1, [])
        self.scheduler_loop(1, [])  # Need 2 run for get then consume)
        self.update_broker()

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        # The result was from a passive check -> check_type=1
        goodresponse = """test_host_0;test_ok_0;1;1
"""
        print response
        self.assertEqual(goodresponse, response )

        for service in self.sched.services:
            objlist.append([service, 2, 'CRIT'])
        self.scheduler_loop(1, objlist)
        self.update_broker()

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        # The last check was an active check -> check_type=0
        goodresponse = """test_host_0;test_ok_0;2;0
"""
        print response
        self.assertEqual(goodresponse, response )

    def test_childs(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET hosts
Columns: childs
Filter: name = test_host_0
OutputFormat: csv
KeepAlive: on
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET hosts
Columns: childs
Filter: name = test_router_0
OutputFormat: csv
KeepAlive: on
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO


    def test_nonsense(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()

        # non-existing filter-column
        request = """GET hosts
Columns: name state
Filter: serialnumber = localhost
"""
        goodresponse = """Invalid GET request, no such column 'serialnumber'
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response", response
        self.assertEqual(response, goodresponse)

        # this time as fixed16
        request = """GET hosts
Columns: name state
Filter: serialnumber = localhost
ResponseHeader: fixed16
"""
        goodresponse = """450          51
Invalid GET request, no such column 'serialnumber'
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response", response
        self.assertEqual(goodresponse, response )

        # invalid filter-clause. attribute, operator missing
        request = """GET hosts
Columns: name state
Filter: localhost
ResponseHeader: fixed16
"""
        goodresponse = """452          55
Completely invalid GET request \'invalid Filter header\'
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertEqual(goodresponse, response )

        # non-existing table
        request = """GET hostshundsglumpvarreckts
Columns: name state
ResponseHeader: fixed16
"""
        goodresponse = """404          62
Invalid GET request, no such table 'hostshundsglumpvarreckts'
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertEqual(goodresponse, response )

    def test_bad_column(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET services
Columns: host_name wrdlbrmpft description
Filter: host_name = test_host_0
OutputFormat: csv
KeepAlive: on
ResponseHeader: off
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """test_host_0;;test_ok_0
"""
        self.assertEqual(good_response, response )
        request = """GET services
Columns: host_name wrdlbrmpft description
Filter: host_name = test_host_0
OutputFormat: json
KeepAlive: on
ResponseHeader: off
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """[["test_host_0","","test_ok_0"]]
"""
        self.assertEqual(good_response, response )

    def test_servicesbyhostgroup(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET servicesbyhostgroup
Filter: host_groups >= allhosts
Columns: hostgroup_name host_name service_description groups
OutputFormat: csv
KeepAlive: on
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        # Again, but without filter
        request = """GET servicesbyhostgroup
Columns: hostgroup_name host_name service_description groups
OutputFormat: csv
KeepAlive: on
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

    def test_hostsbygroup(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET hostsbygroup
ColumnHeaders: on
Columns: host_name hostgroup_name
Filter: groups >= allhosts
OutputFormat: csv
KeepAlive: on
ResponseHeader: fixed16
"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

    def test_delegate_to_host(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET services
Columns: host_name description state state_type plugin_output host_state host_state_type host_plugin_output
OutputFormat: csv
Filter: host_state != 0
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertEqual('\n', response )
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 2, 'BAD']])
        self.update_broker()
        request = """GET services
Columns: host_name description state state_type plugin_output host_state host_state_type host_plugin_output
OutputFormat: csv
Filter: host_state != 0
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertEqual('test_host_0;test_ok_0;2;1;BAD;1;1;DOWN\n', response )

    def test_status(self):
        self.print_header()
        now = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(2, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 2, 'BAD']])
        self.update_broker(True)
        #---------------------------------------------------------------
        # get the full hosts table
        #---------------------------------------------------------------
        request = 'GET hosts'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        #---------------------------------------------------------------
        # get only the host names and addresses
        #---------------------------------------------------------------
        request = 'GET hosts\nColumns: name address groups\nColumnHeaders: on'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        #---------------------------------------------------------------
        # query_1
        #---------------------------------------------------------------
        request = 'GET contacts'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_1_______________\n%s\n%s\n' % (request, response)
        # TODO

        #---------------------------------------------------------------
        # query_2
        #---------------------------------------------------------------
        request = 'GET contacts\nColumns: name alias'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_2_______________\n%s\n%s\n' % (request, response)
        # TODO

        #---------------------------------------------------------------
        # query_3
        #---------------------------------------------------------------
        #self.scheduler_loop(3, svc, 2, 'BAD')
        request = 'GET services\nColumns: host_name description state\nFilter: state = 2\nColumnHeaders: on'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_3_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('host_name;description;state\ntest_host_0;test_ok_0;2\n', response )
        request = 'GET services\nColumns: host_name description state\nFilter: state = 2'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_3_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('test_host_0;test_ok_0;2\n', response )
        request = 'GET services\nColumns: host_name description state\nFilter: state = 0'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_3_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('\n', response )
        duration = 180
        now = time.time()
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;0;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        self.update_broker(True)
        self.scheduler_loop(1, [[svc, 0, 'OK']])
        self.update_broker(True)
        self.scheduler_loop(3, [[svc, 2, 'BAD']])
        self.update_broker(True)
        request = 'GET services\nColumns: host_name description scheduled_downtime_depth\nFilter: state = 2\nFilter: scheduled_downtime_depth = 1'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_3_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('test_host_0;test_ok_0;1\n', response )

        #---------------------------------------------------------------
        # query_4
        #---------------------------------------------------------------
        request = 'GET services\nColumns: host_name description state\nFilter: state = 2\nFilter: in_notification_period = 1\nAnd: 2\nFilter: state = 0\nOr: 2\nFilter: host_name = test_host_0\nFilter: description = test_ok_0\nAnd: 3\nFilter: contacts >= harri\nFilter: contacts >= test_contact\nOr: 3'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_4_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('test_host_0;test_ok_0;2\n', response )

        #---------------------------------------------------------------
        # query_6
        #---------------------------------------------------------------
        request = 'GET services\nStats: state = 0\nStats: state = 1\nStats: state = 2\nStats: state = 3'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_6_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('0;0;1;0\n', response )

        #---------------------------------------------------------------
        # query_7
        #---------------------------------------------------------------
        request = 'GET services\nStats: state = 0\nStats: state = 1\nStats: state = 2\nStats: state = 3\nFilter: contacts >= test_contact'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_6_______________\n%s\n%s\n' % (request, response)
        self.assertEqual('0;0;1;0\n', response )

        # service-contact_groups
        request = 'GET services\nFilter: description = test_ok_0\nFilter: host_name = test_host_0\nColumns: contacts contact_groups\nOutputFormat: python\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'query_contact_groups_______________\n%s\n%s\n' % (request, response)
        pyresponse = eval(response)
        self.assert_(isinstance(pyresponse[0][0], list))
        self.assert_(isinstance(pyresponse[0][1], list))
        self.assert_(isinstance(pyresponse[0][0][0], basestring))
        self.assert_(isinstance(pyresponse[0][1][0], basestring))


    def test_modified_attributes(self):
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        self.scheduler_loop(2, [[host, 0, 'UP'], [svc, 0, 'OK']])
        self.update_broker()

        request = """GET services
Columns: host_name description modified_attributes modified_attributes_list
Filter: host_name = test_host_0
Filter: description = test_ok_0
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response1", response
        self.assertEqual("test_host_0;test_ok_0;0;\n", response )

        now = time.time()
        cmd = "[%lu] DISABLE_SVC_CHECK;test_host_0;test_ok_0" % now
        self.sched.run_external_command(cmd)
        self.sched.get_new_actions()
        self.scheduler_loop(2, [[host, 0, 'UP'], [svc, 0, 'OK']])
        self.update_broker()
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response2", response
        self.assertEqual('test_host_0;test_ok_0;2;active_checks_enabled\n', response )
        lssvc = self.livestatus_broker.datamgr.get_service("test_host_0", "test_ok_0")
        print "ma", lssvc.modified_attributes
        now = time.time()
        cmd = "[%lu] DISABLE_SVC_NOTIFICATIONS;test_host_0;test_ok_0" % now
        self.sched.run_external_command(cmd)
        self.sched.get_new_actions()
        self.scheduler_loop(2, [[host, 0, 'UP'], [svc, 0, 'OK']])
        self.update_broker()
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response3", response
        self.assertEqual('test_host_0;test_ok_0;3;notifications_enabled,active_checks_enabled\n', response )
        print "ma", lssvc.modified_attributes

    def test_json(self):
        self.print_header()
        print "got initial broks"
        now = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(2, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 2, 'BAD']])
        self.update_broker()
        request = 'GET services\nColumns: host_name description state\nOutputFormat: json'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'json wo headers__________\n%s\n%s\n' % (request, response)
        self.assertEqual('[["test_host_0","test_ok_0",2]]\n', response )
        request = 'GET services\nColumns: host_name description state\nOutputFormat: json\nColumnHeaders: on'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print 'json with headers__________\n%s\n%s\n' % (request, response)
        self.assertEqual('[["host_name","description","state"],["test_host_0","test_ok_0",2]]\n', response )
        # 100% mklivesttaus: self.assertEqual('[["host_name","description","state"],\n["test_host_0","test_ok_0",2]]\n', response )

    def test_thruk(self):
        self.print_header()
        now = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(2, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 2, 'BAD']])
        self.update_broker()
        #---------------------------------------------------------------
        # get the full hosts table
        #---------------------------------------------------------------
        request = """GET hosts
Stats: name !=
Stats: check_type = 0
Stats: check_type = 1
Stats: has_been_checked = 1
Stats: state = 0
StatsAnd: 2
Stats: has_been_checked = 1
Stats: state = 1
StatsAnd: 2
Stats: has_been_checked = 1
Stats: state = 2
StatsAnd: 2
Stats: has_been_checked = 0
Stats: has_been_checked = 0
Stats: active_checks_enabled = 0
StatsAnd: 2
Stats: has_been_checked = 0
Stats: scheduled_downtime_depth > 0
StatsAnd: 2
Stats: state = 0
Stats: has_been_checked = 1
Stats: active_checks_enabled = 0
StatsAnd: 3
Stats: state = 0
Stats: has_been_checked = 1
Stats: scheduled_downtime_depth > 0
StatsAnd: 3
Stats: state = 1
Stats: has_been_checked = 1
Stats: acknowledged = 1
StatsAnd: 3
Stats: state = 1
Stats: scheduled_downtime_depth > 0
Stats: has_been_checked = 1
StatsAnd: 3
Stats: state = 1
Stats: active_checks_enabled = 0
Stats: has_been_checked = 1
StatsAnd: 3
Stats: state = 1
Stats: active_checks_enabled = 1
Stats: acknowledged = 0
Stats: scheduled_downtime_depth = 0
Stats: has_been_checked = 1
StatsAnd: 5
Stats: state = 2
Stats: acknowledged = 1
Stats: has_been_checked = 1
StatsAnd: 3
Stats: state = 2
Stats: scheduled_downtime_depth > 0
Stats: has_been_checked = 1
StatsAnd: 3
Stats: state = 2
Stats: active_checks_enabled = 0
StatsAnd: 2
Stats: state = 2
Stats: active_checks_enabled = 1
Stats: acknowledged = 0
Stats: scheduled_downtime_depth = 0
Stats: has_been_checked = 1
StatsAnd: 5
Stats: is_flapping = 1
Stats: flap_detection_enabled = 0
Stats: notifications_enabled = 0
Stats: event_handler_enabled = 0
Stats: active_checks_enabled = 0
Stats: accept_passive_checks = 0
Stats: state = 1
Stats: childs !=
StatsAnd: 2
Separators: 10 59 44 124
ResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET comments
Columns: host_name source type author comment entry_time entry_type expire_time
Filter: service_description ="""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET hosts
Columns: comments has_been_checked state name address acknowledged notifications_enabled active_checks_enabled is_flapping scheduled_downtime_depth is_executing notes_url_expanded action_url_expanded icon_image_expanded icon_image_alt last_check last_state_change plugin_output next_check long_plugin_output
Separators: 10 59 44 124
ResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

        duration = 180
        now = time.time()
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_warning_00;%d;%d;0;0;%d;lausser;blablubsvc" % (now, now, now + duration, duration)
        print cmd
        self.sched.run_external_command(cmd)
        cmd = "[%lu] SCHEDULE_HOST_DOWNTIME;test_host_0;%d;%d;0;0;%d;lausser;blablubhost" % (now, now, now + duration, duration)
        print cmd
        self.sched.run_external_command(cmd)
        self.update_broker()
        self.scheduler_loop(1, [[svc, 0, 'OK']])
        self.update_broker()
        self.scheduler_loop(3, [[svc, 2, 'BAD']])
        self.update_broker()
        request = """GET downtimes
Filter: service_description =
Columns: author comment end_time entry_time fixed host_name id start_time
Separators: 10 59 44 124"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        expected = "lausser;blablubhost;"
        self.assertEqual(expected, response[:len(expected)])
        # TODO

        request = """GET comments
Filter: service_description =
Columns: author comment
Separators: 10 59 44 124
ResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET services
Filter: has_been_checked = 1
Filter: check_type = 0
Stats: sum has_been_checked
Stats: sum latency
Separators: 10 59 44 124
ResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

        request = """GET services
Filter: has_been_checked = 1
Filter: check_type = 0
Stats: sum has_been_checked
Stats: sum latency
Stats: sum execution_time
Stats: min latency
Stats: min execution_time
Stats: max latency
Stats: max execution_time
Separators: 10 59 44 124
ResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

        request = """GET services\nFilter: has_been_checked = 1\nFilter: check_type = 0\nStats: sum has_been_checked as has_been_checked\nStats: sum latency as latency_sum\nStats: sum execution_time as execution_time_sum\nStats: min latency as latency_min\nStats: min execution_time as execution_time_min\nStats: max latency as latency_max\nStats: max execution_time as execution_time_max\n\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

        request = """GET hostgroups\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET hosts\nColumns: name groups\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET hostgroups\nColumns: name num_services num_services_ok\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

        request = """GET hostgroups\nColumns: name num_services_pending num_services_ok num_services_warn num_services_crit num_services_unknown worst_service_state worst_service_hard_state\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']])
        self.update_broker()
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()

        print "WARNING SOFT;1"
        # worst_service_state 1, worst_service_hard_state 0
        request = """GET hostgroups\nColumns: name num_services_pending num_services_ok num_services_warn num_services_crit num_services_unknown worst_service_state worst_service_hard_state\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        print "WARNING HARD;3"
        # worst_service_state 1, worst_service_hard_state 1
        request = """GET hostgroups\nColumns: name num_services_pending num_services_ok num_services_warn num_services_crit num_services_unknown worst_service_state worst_service_hard_state\nColumnHeaders: on\nResponseHeader: fixed16"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        for s in self.livestatus_broker.livestatus.datamgr.rg.services:
            print "%s %d %s;%d" % (s.state, s.state_id, s.state_type, s.attempt)

    def test_thruk_config(self):
        self.print_header()
        now = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(2, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 2, 'BAD']])
        self.update_broker()
        #---------------------------------------------------------------
        # get the full hosts table
        #---------------------------------------------------------------
        request = 'GET status\nColumns: livestatus_version program_version accept_passive_host_checks accept_passive_service_checks check_external_commands check_host_freshness check_service_freshness enable_event_handlers enable_flap_detection enable_notifications execute_host_checks execute_service_checks last_command_check last_log_rotation nagios_pid obsess_over_hosts obsess_over_services process_performance_data program_start interval_length'
        # Jan/2012 - Columns: accept_passive_host_checks accept_passive_service_checks check_external_commands check_host_freshness check_service_freshness enable_event_handlers enable_flap_detection enable_notifications execute_host_checks execute_service_checks last_command_check last_log_rotation livestatus_version nagios_pid obsess_over_hosts obsess_over_services process_performance_data program_start program_version interval_length
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

    def test_thruk_comments(self):
        self.print_header()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)

        print "downtime was scheduled. check its activity and the comment"
        self.assertEqual(1, len(self.sched.downtimes) )
        self.assertEqual(1, len(svc.downtimes) )
        self.assert_(svc.downtimes[0] in self.sched.downtimes.values())
        self.assert_(svc.downtimes[0].fixed)
        self.assert_(svc.downtimes[0].is_in_effect)
        self.assert_(not svc.downtimes[0].can_be_deleted)
        self.assertEqual(1, len(self.sched.comments) )
        self.assertEqual(1, len(svc.comments) )
        self.assert_(svc.comments[0] in self.sched.comments.values())
        self.assertEqual(svc.comments[0].id, svc.downtimes[0].comment_id )

        now = time.time()
        cmd = "[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;comment" % now
        self.sched.run_external_command(cmd)
        #cmd = "[%lu] ADD_HOST_COMMENT;test_host_0;1;lausser;hcomment" % now
        #self.sched.run_external_command(cmd)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.assertEqual(2, len(self.sched.comments) )
        self.assertEqual(2, len(svc.comments) )

        self.update_broker()
        svc_comment_list = (',').join([str(c.id) for c in svc.comments])

        #request = """GET comments\nColumns: host_name service_description id source type author comment entry_time entry_type persistent expire_time expires\nFilter: service_description !=\nResponseHeader: fixed16\nOutputFormat: json\n"""
        request = """GET services\nColumns: comments host_comments host_is_executing is_executing\nFilter: service_description !=\nResponseHeader: fixed16\nOutputFormat: json\n"""
        response, _ = self.livestatus_broker.livestatus.handle_request(request)
        print "resp (%s) resp" % response
        good_response = """200          17
[[[""" + svc_comment_list + """],[],0,0]]
"""
        print "resp (%s) resp" % response
        print "good (%s) good" % good_response
        self.assertEqual(good_response, response )  # json

        request = """GET services\nColumns: comments host_comments host_is_executing is_executing\nFilter: service_description !=\nResponseHeader: fixed16\n"""
        response, _ = self.livestatus_broker.livestatus.handle_request(request)
        #print response
        good_response = """200           9
""" + svc_comment_list.replace(" ", "") + """;;0;0
"""
        self.assertEqual(good_response, response )  # csv

        request = """GET comments
Columns: author entry_type expires expire_time host_name id persistent service_description source type
Filter: service_description !=
Filter: service_description =
Or: 2
OutputFormat: json
ResponseHeader: fixed16\n"""
        response, _ = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """200         115
[["(Nagios Process)",2,0,0,"test_host_0",%d,0,"test_ok_0",0,2],["lausser",1,0,0,"test_host_0",%d,1,"test_ok_0",1,2]]
""" % (self.sched.comments[1].id, self.sched.comments[2].id)
        print "request", request
        print "response", response
        print "goodresp", good_response
        self.assertEqual(good_response, response )

    def test_thruk_logs(self):
        self.print_header()
        start = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        now = time.time()
        cmd = "[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;comment" % now
        self.sched.run_external_command(cmd)
        time.sleep(1)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        end = time.time()

        # show history for service
        request = """GET log
Columns: time type options state
Filter: time >= """ + str(int(start)) + """
Filter: time <= """ + str(int(end)) + """
Filter: type = SERVICE ALERT
Filter: type = HOST ALERT
Filter: type = SERVICE FLAPPING ALERT
Filter: type = HOST FLAPPING ALERT
Filter: type = SERVICE DOWNTIME ALERT
Filter: type = HOST DOWNTIME ALERT
Or: 6
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
And: 3
Filter: type ~ starting...
Filter: type ~ shutting down...
Or: 3
Filter: current_service_description !=

Filter: service_description =
Filter: host_name !=
And: 2
Filter: service_description =
Filter: host_name =
And: 2
Or: 3"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(self.contains_line(response, 'SERVICE DOWNTIME ALERT;"test_host_0;test_ok_0;STARTED; Service has entered a period of scheduled downtime"'))

    def test_thruk_logs_alerts_summary(self):
        self.print_header()
        start = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        now = time.time()
        cmd = "[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;comment" % now
        self.sched.run_external_command(cmd)
        time.sleep(1)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        end = time.time()
        # is this an error in thruk?

        request = """GET log
Filter: options ~ ;HARD;
Filter: type = HOST ALERT
Filter: time >= 1284056080
Filter: time <= 1284660880
Filter: current_service_description !=
Filter: service_description =
Filter: host_name !=
And: 2
Filter: service_description =
Filter: host_name =
And: 2
Or: 3
Columns: time state state_type host_name service_description current_host_groups current_service_groups plugin_output"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

    def test_thruk_logs_current(self):
        self.print_header()
        start = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        now = time.time()
        cmd = "[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;comment" % now
        self.sched.run_external_command(cmd)
        time.sleep(1)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 0, 'UUP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        ## time.sleep(1)
        ## self.scheduler_loop(3, [[host, 0, 'UP'], [router, 2, 'DOWN'], [svc, 0, 'OK']], do_sleep=False)
        ## self.update_broker()
        end = time.time()

        # show history for service
        request = """GET log
Columns: time type options state current_host_name
Filter: time >= """ + str(int(start)) + """
Filter: time <= """ + str(int(end)) + """
Filter: type = SERVICE ALERT
Filter: type = HOST ALERT
Filter: type = SERVICE FLAPPING ALERT
Filter: type = HOST FLAPPING ALERT
Filter: type = SERVICE DOWNTIME ALERT
Filter: type = HOST DOWNTIME ALERT
Or: 6
Filter: current_host_name = test_host_0
Filter: current_service_description = test_ok_0
And: 2"""
        request = """GET log
Columns: time type options state current_host_name
Filter: time >= """ + str(int(start)) + """
Filter: time <= """ + str(int(end)) + """
Filter: current_host_name = test_host_0
Filter: current_service_description = test_ok_0
And: 2"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

    def test_thruk_logs_utf8(self):
        self.print_header()
        start = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        # -----------------------------------------------------------------> HERE is the UTF8 char :)
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, u'WARNINGé']])
        self.update_broker()
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = u"[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablubé" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        now = time.time()
        cmd = "u[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;commenté" % now
        self.sched.run_external_command(cmd)
        time.sleep(1)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 0, 'UUP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        ## time.sleep(1)
        ## self.scheduler_loop(3, [[host, 0, 'UP'], [router, 2, 'DOWN'], [svc, 0, 'OK']], do_sleep=False)
        ## self.update_broker()
        end = time.time()

        # show history for service
        request = """GET log
Columns: time type options state current_host_name
Filter: time >= """ + str(int(start)) + """
Filter: time <= """ + str(int(end)) + """
Filter: type = SERVICE ALERT
Filter: type = HOST ALERT
Filter: type = SERVICE FLAPPING ALERT
Filter: type = HOST FLAPPING ALERT
Filter: type = SERVICE DOWNTIME ALERT
Filter: type = HOST DOWNTIME ALERT
Or: 6
Filter: current_host_name = test_host_0
Filter: current_service_description = test_ok_0
And: 2"""
        request = """GET log
Columns: time type options state current_host_name
Filter: time >= """ + str(int(start)) + """
Filter: time <= """ + str(int(end)) + """
Filter: current_host_name = test_host_0
Filter: current_service_description = test_ok_0
And: 2"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        #print response

    def test_thruk_tac_svc(self):
        self.print_header()
        self.update_broker()

        start = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(3, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        duration = 600
        now = time.time()
        # downtime valid for the next 2 minutes
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;1;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        now = time.time()
        cmd = "[%lu] ADD_SVC_COMMENT;test_host_0;test_ok_0;1;lausser;comment" % now
        self.sched.run_external_command(cmd)
        time.sleep(1)
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 2, 'DOWN'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        time.sleep(1)
        self.scheduler_loop(3, [[host, 0, 'UUP'], [router, 0, 'UP'], [svc, 0, 'OK']], do_sleep=False)
        self.update_broker()
        ## time.sleep(1)
        ## self.scheduler_loop(3, [[host, 0, 'UP'], [router, 2, 'DOWN'], [svc, 0, 'OK']], do_sleep=False)
        ## self.update_broker()
        end = time.time()

        # show history for service
        request = """GET services
Filter: has_been_checked = 1
Filter: check_type = 0
Stats: sum has_been_checked
Stats: sum latency
Stats: sum execution_time
Stats: min latency
Stats: min execution_time
Stats: max latency
Stats: max execution_time"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO


    def test_columns(self):
        self.print_header()
        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET columns"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # TODO

    def test_scheduler_table(self):
        self.print_header()
        self.update_broker()

        creation_tab = {'scheduler_name': 'scheduler-1', 'address': 'localhost', 'spare': '0'}
        schedlink = SchedulerLink(creation_tab)
        schedlink.alive = True
        b = schedlink.get_initial_status_brok()
        self.sched.add(b)
        creation_tab = {'scheduler_name': 'scheduler-2', 'address': 'othernode', 'spare': '1'}
        schedlink = SchedulerLink(creation_tab)
        schedlink.alive = True
        b2 = schedlink.get_initial_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET schedulers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare;weight
othernode;1;scheduler-2;7768;1;1
localhost;1;scheduler-1;7768;0;1
"""
        print response, 'FUCK'
        print "FUCK", response, "TOTO"
        self.assert_(self.lines_equal(response, good_response))

        # Now we update a scheduler state and we check
        # here the N2
        schedlink.alive = False
        b = schedlink.get_update_status_brok()
        self.sched.add(b)
        self.update_broker()
        request = """GET schedulers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """address;alive;name;port;spare;weight
othernode;0;scheduler-2;7768;1;1
localhost;1;scheduler-1;7768;0;1
"""
        self.assert_(self.lines_equal(response, good_response))

    def test_reactionner_table(self):
        self.print_header()
        self.update_broker()
        creation_tab = {'reactionner_name': 'reactionner-1', 'address': 'localhost', 'spare': '0'}
        reac = ReactionnerLink(creation_tab)
        reac.alive = True
        b = reac.get_initial_status_brok()
        self.sched.add(b)
        creation_tab = {'reactionner_name': 'reactionner-2', 'address': 'othernode', 'spare': '1'}
        reac = ReactionnerLink(creation_tab)
        reac.alive = True
        b2 = reac.get_initial_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET reactionners"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;reactionner-1;7769;0
othernode;1;reactionner-2;7769;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

        # Now the update part
        reac.alive = False
        b2 = reac.get_update_status_brok()
        self.sched.add(b2)
        self.update_broker()
        request = """GET reactionners"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;reactionner-1;7769;0
othernode;0;reactionner-2;7769;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

    def test_poller_table(self):
        self.print_header()
        self.update_broker()

        creation_tab = {'poller_name': 'poller-1', 'address': 'localhost', 'spare': '0'}
        pol = PollerLink(creation_tab)
        pol.alive = True
        b = pol.get_initial_status_brok()
        self.sched.add(b)
        creation_tab = {'poller_name': 'poller-2', 'address': 'othernode', 'spare': '1'}
        pol = PollerLink(creation_tab)
        pol.alive = True
        b2 = pol.get_initial_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET pollers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;poller-1;7771;0
othernode;1;poller-2;7771;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

        # Now the update part
        pol.alive = False
        b2 = pol.get_update_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET pollers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;poller-1;7771;0
othernode;0;poller-2;7771;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

    def test_broker_table(self):
        self.print_header()
        self.update_broker()

        creation_tab = {'broker_name': 'broker-1', 'address': 'localhost', 'spare': '0'}
        pol = BrokerLink(creation_tab)
        pol.alive = True
        b = pol.get_initial_status_brok()
        self.sched.add(b)
        creation_tab = {'broker_name': 'broker-2', 'address': 'othernode', 'spare': '1'}
        pol = BrokerLink(creation_tab)
        pol.alive = True
        b2 = pol.get_initial_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET brokers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;broker-1;7772;0
othernode;1;broker-2;7772;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

        # Now the update part
        pol.alive = False
        b2 = pol.get_initial_status_brok()
        self.sched.add(b2)

        self.update_broker()
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET brokers"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """address;alive;name;port;spare
localhost;1;broker-1;7772;0
othernode;0;broker-2;7772;1
"""
        print response == good_response
        self.assert_(self.lines_equal(response, good_response))

    def test_problems_table(self):
        self.print_header()
        self.update_broker()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        # We need the dependency here, so comment it out!!!!!!
        #host.act_depend_of = [] # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        #router.act_depend_of = [] # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults

        lshost = self.livestatus_broker.rg.hosts.find_by_name("test_host_0")
        lsrouter = self.livestatus_broker.rg.hosts.find_by_name("test_router_0")
        lssvc = self.livestatus_broker.rg.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        print "       scheduler   livestatus"
        print "host   %9s   %s" % (host.is_problem, lshost.is_problem)
        print "router %9s   %s" % (router.is_problem, lsrouter.is_problem)
        print "svc    %9s   %s" % (svc.is_problem, lssvc.is_problem)
        self.scheduler_loop(4, [[host, 2, 'DOWN'], [router, 2, 'DOWN'], [svc, 2, 'BAD']])
        print "       scheduler   livestatus"
        print "host   %9s   %s" % (host.is_problem, lshost.is_problem)
        print "router %9s   %s" % (router.is_problem, lsrouter.is_problem)
        print "svc    %9s   %s" % (svc.is_problem, lssvc.is_problem)
        print "Is router a problem?", router.is_problem, router.state, router.state_type
        print "Is host a problem?", host.is_problem, host.state, host.state_type
        print "Is service a problem?", svc.is_problem, svc.state, svc.state_type
        self.update_broker()
        print "All", self.livestatus_broker.datamgr.rg.hosts
        for h in self.livestatus_broker.datamgr.rg.hosts:
            print h.get_dbg_name(), h.is_problem

        print "       scheduler   livestatus"
        print "host   %9s   %s" % (host.is_problem, lshost.is_problem)
        print "router %9s   %s" % (router.is_problem, lsrouter.is_problem)
        print "svc    %9s   %s" % (svc.is_problem, lssvc.is_problem)
        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        request = """GET problems"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "FUCK", response
        good_response = """impacts;source
test_host_0/test_ok_0,test_host_0;test_router_0
"""
        print response == good_response
        self.assertEqual(good_response, response )

    def test_parent_childs_dep_lists(self):
        self.print_header()
        self.update_broker()
        host = self.sched.hosts.find_by_name("test_host_0")
        router = self.sched.hosts.find_by_name("test_router_0")
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")

        #---------------------------------------------------------------
        # get the columns meta-table
        #---------------------------------------------------------------
        # first test if test_router_0 is in the host parent list
        request = 'GET hosts\nColumns: host_name parent_dependencies\nFilter: host_name = test_host_0\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """test_host_0;test_router_0"""
        self.assertEqual(good_response.strip(), response.strip() )

        # Now check if host is in the child router list
        request = 'GET hosts\nColumns: host_name child_dependencies\nFilter: host_name = test_router_0\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """test_router_0;test_host_0"""
        self.assertEqual(good_response.strip(), response.strip() )

        # Now check with the service
        request = 'GET hosts\nColumns: host_name child_dependencies\nFilter: host_name = test_host_0\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """test_host_0;test_host_0/test_ok_0"""
        self.assertEqual(good_response.strip(), response.strip() )

        # And check the parent for the service
        request = 'GET services\nColumns: parent_dependencies\nFilter: host_name = test_host_0\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = """test_host_0"""
        self.assertEqual(good_response.strip(), response.strip() )

    def test_limit(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        #---------------------------------------------------------------
        # get the full hosts table
        #---------------------------------------------------------------
        request = 'GET hosts\nColumns: host_name\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """test_host_0
test_router_0
"""
        self.assert_(self.lines_equal(response, good_response))

        request = 'GET hosts\nColumns: host_name\nLimit: 1\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        good_response = """test_host_0
"""
        # it must be test_host_0 because with Limit: the output is
        # alphabetically ordered
        self.assertEqual(good_response, response )

    def test_problem_impact_in_host_service(self):
        self.print_header()
        now = time.time()
        self.update_broker()

        host_router_0 = self.sched.hosts.find_by_name("test_router_0")
        host_router_0.checks_in_progress = []

        # Then initialize host under theses routers
        host_0 = self.sched.hosts.find_by_name("test_host_0")
        host_0.checks_in_progress = []

        all_hosts = [host_router_0, host_0]
        all_routers = [host_router_0]
        all_servers = [host_0]

        print "- 4 x UP -------------------------------------"
        self.scheduler_loop(1, [[host_router_0, 0, 'UP'], [host_0, 0, 'UP']], do_sleep=False)
        self.scheduler_loop(1, [[host_router_0, 1, 'DOWN']], do_sleep=False)
        self.scheduler_loop(1, [[host_router_0, 1, 'DOWN']], do_sleep=False)
        self.scheduler_loop(1, [[host_router_0, 1, 'DOWN']], do_sleep=False)
        self.scheduler_loop(1, [[host_router_0, 1, 'DOWN']], do_sleep=False)
        self.scheduler_loop(1, [[host_router_0, 1, 'DOWN']], do_sleep=False)

        # Max attempt is reach, should be HARD now
        for h in all_routers:
            self.assertEqual('DOWN', h.state )
            self.assertEqual('HARD', h.state_type )

        for b in self.sched.broks.values():
            print "All broks", b.type, b
            if b.type == 'update_host_status':
                print "***********"
                #print "Impacts", b.data['impacts']
                #print "Sources",  b.data['source_problems']

        for b in host_router_0.broks:
            print " host_router_0.broks", b

        self.update_broker()

        print "source de host_0", host_0.source_problems
        for i in host_0.source_problems:
            print "source", i.get_name()
        print "impacts de host_router_0", host_router_0.impacts
        for i in host_router_0.impacts:
            print "impact", i.get_name()

        #---------------------------------------------------------------
        # get the full hosts table
        #---------------------------------------------------------------
        print "Got source problems"
        request = 'GET hosts\nColumns: host_name is_impact source_problems\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "moncullulu2", response
        good_response = """test_router_0;0;
test_host_0;1;test_router_0
"""
        self.assert_(self.lines_equal(response, good_response))

        print "Now got impact"
        request = 'GET hosts\nColumns: host_name is_problem impacts\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "moncululu", response
        good_response = """test_router_0;1;test_host_0,test_host_0|test_ok_0
test_host_0;0;"""
        self.assert_(self.lines_equal(response.strip(), good_response.strip()))

        request = 'GET hosts\nColumns: host_name\nLimit: 1\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response(%s)" % response
        good_response = """test_host_0
"""
        print "goodresp(%s)" % good_response
        # it must be test_host_0 because with Limit: the output is
        # alphabetically ordered
        self.assertEqual(good_response, response )

    def test_thruk_servicegroup(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        #---------------------------------------------------------------
        # get services of a certain servicegroup
        # test_host_0/test_ok_0 is in
        #   servicegroup_01,ok via service.servicegroups
        #   servicegroup_02 via servicegroup.members
        #---------------------------------------------------------------
        request = """GET services
Columns: host_name service_description
Filter: groups >= servicegroup_01
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          22
test_host_0;test_ok_0
""")
        request = """GET services
Columns: host_name service_description
Filter: groups >= servicegroup_02
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          22
test_host_0;test_ok_0
""")

    def test_host_and_service_eventhandler(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        host = self.sched.hosts.find_by_name("test_host_0")
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        self.assertEqual(True, host.event_handler_enabled )
        self.assertEqual(True, svc.event_handler_enabled )

        request = """GET services
Columns: host_name service_description event_handler_enabled event_handler
Filter: host_name = test_host_0
Filter: description = test_ok_0
OutputFormat: csv
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_("""test_host_0;test_ok_0;1;eventhandler
""")
        self.assertEqual("%s;%s;%d;%s\n" % (svc.host_name, svc.service_description, from_bool_to_int(svc.event_handler_enabled), svc.event_handler.get_name()), response )

        request = """GET hosts
Columns: host_name event_handler_enabled event_handler
Filter: host_name = test_host_0
OutputFormat: csv
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_("""test_host_0;1;eventhandler
""")
        self.assertEqual("%s;%d;%s\n" % (host.host_name, from_bool_to_int(host.event_handler_enabled), host.event_handler.get_name()), response )

    def test_is_executing(self):
        self.print_header()
        #---------------------------------------------------------------
        # make sure that the is_executing flag is updated regularly
        #---------------------------------------------------------------
        now = time.time()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults

        for loop in range(1, 2):
            print "processing check", loop
            self.show_broks("update_in_checking")
            svc.update_in_checking()
            self.show_broks("fake_check")
            self.fake_check(svc, 2, 'BAD')
            self.show_broks("sched.consume_results")
            self.sched.consume_results()
            self.show_broks("sched.get_new_actions")
            self.sched.get_new_actions()
            self.show_broks("sched.get_new_broks")
            self.sched.get_new_broks()
            self.show_broks("sched.delete_zombie_checks")
            self.sched.delete_zombie_checks()
            self.show_broks("sched.delete_zombie_actions")
            self.sched.delete_zombie_actions()
            self.show_broks("sched.get_to_run_checks")
            checks = self.sched.get_to_run_checks(True, False)
            self.show_broks("sched.get_to_run_checks")
            actions = self.sched.get_to_run_checks(False, True)
            #self.show_actions()
            for a in actions:
                a.status = 'inpoller'
                a.check_time = time.time()
                a.exit_status = 0
                self.sched.put_results(a)
            #self.show_actions()

            svc.checks_in_progress = []
            self.show_broks("sched.update_downtimes_and_comments")
            self.sched.update_downtimes_and_comments()
            time.sleep(5)

        print "-------------------------------------------------"
        for brok in sorted(self.sched.broks.values(), lambda x, y: x.id - y.id):
            if re.compile('^service_').match(brok.type):
                print "BROK:", brok.type
                print "BROK   ", brok.data['in_checking']
        self.update_broker()
        print "-------------------------------------------------"
        request = 'GET services\nColumns: service_description is_executing\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response

    def test_pnp_path(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        #---------------------------------------------------------------
        # pnp_path is a parameter for the module
        # column pnpgraph_present checks if a file
        #  <pnp_path>/host/service.xml
        #  <pnp_path>/host/_HOST_.xml
        # exists
        #---------------------------------------------------------------
        pnp_path = self.livestatus_broker.pnp_path
        try:
            os.removedirs(pnp_path)
        except:
            pass
        else:
            print "there is no spool dir", pnp_path

        request = """GET services
Columns: host_name service_description pnpgraph_present
OutputFormat: csv
ResponseHeader: fixed16
"""
        requesth = """GET hosts
Columns: host_name pnpgraph_present
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200          24
test_host_0;test_ok_0;0
""")
        #self.assert_(not self.livestatus_broker.livestatus.pnp_path)

        try:
            os.makedirs(pnp_path)
            print "there is an empty spool dir", pnp_path
        except:
            pass

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200          24
test_host_0;test_ok_0;0
""")
        print "pnp_path", self.livestatus_broker.livestatus.pnp_path
        print "pnp_path", pnp_path + "/"
        self.assertEqual(pnp_path, self.livestatus_broker.livestatus.pnp_path )

        try:
            os.makedirs(pnp_path + '/test_host_0')
            open(pnp_path + '/test_host_0/_HOST_.xml', 'w').close()
            open(pnp_path + '/test_host_0/test_ok_0.xml', 'w').close()
            print "there is a spool dir with data", pnp_path
        except:
            pass

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200          24
test_host_0;test_ok_0;1
""")
        response, keepalive = self.livestatus_broker.livestatus.handle_request(requesth)
        print response
        goodresponse = """200          30
test_router_0;0
test_host_0;1
"""
        self.assert_(self.lines_equal(response, goodresponse))

    def test_thruk_action_notes_url_icon_image(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        print "HIER WIE GO!!!!"
        request = """GET services
Columns: host_name service_description action_url
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertRegex(response, """200          79
test_host_0;test_ok_0;/[a-z]*/pnp/index.php\?host=\$HOSTNAME\$&srv=\$SERVICEDESC\$
""")

        request = """GET services
Columns: host_name service_description action_url_expanded
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertRegex(response, """200          76
test_host_0;test_ok_0;/[a-z]*/pnp/index.php\?host=test_host_0&srv=test_ok_0
""")

        request = """GET services
Columns: host_name service_description icon_image_expanded
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200          79
test_host_0;test_ok_0;../../docs/images/tip.gif?host=test_host_0&srv=test_ok_0
""")

        request = """GET services
Columns: host_name service_description notes_url_expanded
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertRegex(response, """200          67
test_host_0;test_ok_0;/[a-z]*/wiki/doku.php/test_host_0/test_ok_0
""")

        request = """GET hosts
Columns: host_name action_url_expanded
Filter: host_name = test_host_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertRegex(response, """200          52
test_host_0;/[a-z]*/pnp/index.php\?host=test_host_0
""")

        request = """GET hosts
Columns: host_name icon_image_expanded
Filter: host_name = test_router_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200          62
test_router_0;../../docs/images/switch.png?host=test_router_0
""")

        request = """GET hosts
Columns: host_name notes_url_expanded
Filter: host_name = test_host_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertRegex(response, """200          47
test_host_0;/[a-z]*/wiki/doku.php/test_host_0
""")

    def test_thruk_action_notes_url_icon_image_complicated(self):
        self.print_header()
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.action_url = "/pnp4nagios/index.php/graph?host=$HOSTNAME$&srv=$SERVICEDESC$' class='tips' rel='/pnp4nagios/index.php/popup?host=$HOSTNAME$&srv=$SERVICEDESC$"
        self.sched.get_and_register_status_brok(svc)
        now = time.time()
        self.update_broker()
        request = """GET services
Columns: host_name service_description action_url
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200         165
test_host_0;test_ok_0;/pnp4nagios/index.php/graph?host=$HOSTNAME$&srv=$SERVICEDESC$' class='tips' rel='/pnp4nagios/index.php/popup?host=$HOSTNAME$&srv=$SERVICEDESC$
""")
        request = """GET services
Columns: host_name service_description action_url_expanded
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """200         159
test_host_0;test_ok_0;/pnp4nagios/index.php/graph?host=test_host_0&srv=test_ok_0' class='tips' rel='/pnp4nagios/index.php/popup?host=test_host_0&srv=test_ok_0
""")

    def test_thruk_custom_variables(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        request = """GET hosts
Columns: host_name custom_variable_names custom_variable_values
Filter: host_name = test_host_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          42
test_host_0;OSLICENSE,OSTYPE;gpl,gnulinux
""")

        request = """GET services
Columns: host_name service_description custom_variable_names custom_variable_values
Filter: host_name = test_host_0
Filter: service_description = test_ok_0
OutputFormat: csv
ResponseHeader: fixed16
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          41
test_host_0;test_ok_0;CUSTNAME;custvalue
""")

    def test_multisite_hostgroup_alias(self):
        self.print_header()
        self.update_broker()
        a_h0 = self.sched.hosts.find_by_name("test_host_0")
        a_hg01 = self.sched.hostgroups.find_by_name("hostgroup_01")
        b_hg01 = self.livestatus_broker.rg.hostgroups.find_by_name("hostgroup_01")
        # must have hostgroup_alias_01
        print a_hg01.hostgroup_name, a_hg01.alias
        print b_hg01.hostgroup_name, b_hg01.alias
        self.assertEqual(b_hg01.hostgroup_name, a_hg01.hostgroup_name )
        self.assertEqual(b_hg01.alias, a_hg01.alias )
        request = """GET hostsbygroup
Columns: host_name host_alias hostgroup_name hostgroup_alias
Filter: host_name = test_host_0
OutputFormat: csv
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """test_host_0;up_0;allhosts;All Hosts
test_host_0;up_0;hostgroup_01;hostgroup_alias_01
test_host_0;up_0;up;All Up Hosts
""")

        request = """GET hostsbygroup
Columns: host_name hostgroup_name host_services_with_state host_services
Filter: host_name = test_host_0
OutputFormat: csv
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(response == """test_host_0;allhosts;test_ok_0|0|0;test_ok_0
test_host_0;hostgroup_01;test_ok_0|0|0;test_ok_0
test_host_0;up;test_ok_0|0|0;test_ok_0
""")

    def test_multisite_in_check_period(self):
        self.print_header()
        self.update_broker()
        # timeperiods must be manipulated in the broker, because status-broks
        # contain timeperiod names, not objects.
        lshost = self.livestatus_broker.datamgr.get_host("test_host_0")
        now = time.time()
        localnow = time.localtime(now)
        if localnow[5] > 45:
            time.sleep(15)
        nextminute = time.localtime(time.time() + 60)
        tonextminute = '%s 00:00-%02d:%02d' % (['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][nextminute[6]], nextminute[3], nextminute[4])
        fromnextminute = '%s %02d:%02d-23:59' % (['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][nextminute[6]], nextminute[3], nextminute[4])

        lshost.notification_period = Timeperiod()
        lshost.notification_period.resolve_daterange(lshost.notification_period.dateranges, tonextminute)
        lshost.check_period = Timeperiod()
        lshost.check_period.resolve_daterange(lshost.check_period.dateranges, fromnextminute)
        self.update_broker()
        print "now it is", time.asctime()
        print "notification_period is", tonextminute
        print "check_period is", fromnextminute
        request = """GET hosts
Columns: host_name in_notification_period in_check_period
Filter: host_name = test_host_0
OutputFormat: csv
ResponseHeader: fixed16
"""

        # inside notification_period, outside check_period
        time.sleep(5)
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          16
test_host_0;1;0
""")
        time.sleep(60)
        # a minute later it's the other way round
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assert_(response == """200          16
test_host_0;0;1
""")

    def test_thruk_log_current_groups(self):
        self.print_header()
        now = time.time()
        self.update_broker()
        b = Brok('log', {'log': "[%lu] EXTERNAL COMMAND: [%lu] DISABLE_NOTIFICATIONS" % (now, now)})
        self.livestatus_broker.manage_brok(b)
        b = Brok('log', {'log': "[%lu] EXTERNAL COMMAND: [%lu] STOP_EXECUTING_SVC_CHECKS" % (now, now)})
        self.livestatus_broker.manage_brok(b)
        self.update_broker()
        host = self.sched.hosts.find_by_name("test_host_0")
        host.checks_in_progress = []
        host.act_depend_of = []  # ignore the router
        router = self.sched.hosts.find_by_name("test_router_0")
        router.checks_in_progress = []
        router.act_depend_of = []  # ignore the router
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        svc.checks_in_progress = []
        svc.act_depend_of = []  # no hostchecks on critical checkresults
        self.update_broker()
        self.scheduler_loop(1, [[host, 0, 'UP'], [router, 0, 'UP'], [svc, 1, 'WARNING']])
        self.update_broker()
        # select messages which are not host or service related. current_service_groups must be an empty list
        request = """GET log
Filter: current_host_name =
Filter: current_service_description =
And: 2
Columns: message current_service_groups
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        request = """GET log
Filter: current_host_name =
Filter: current_service_description =
And: 2
Columns: message current_service_groups
OutputFormat: json
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        good_response = "[[\"[%lu] EXTERNAL COMMAND: [%lu] DISABLE_NOTIFICATIONS\",[]],[\"[%lu] EXTERNAL COMMAND: [%lu] STOP_EXECUTING_SVC_CHECKS\",[]]]\n" % (now, now, now, now)
        pyresponse = eval(response)
        response = [l[0] for l in pyresponse if not ("Info" in l[0] or "Warning" in l[0] or "Debug" in l[0])]
        print "pyth", pyresponse
        print "good", good_response
        print "resp", response
        self.assertEqual(2, len(response) )
        self.assert_("DISABLE_NOTIFICATIONS" in response[0])
        self.assert_("STOP_EXECUTING_SVC_CHECKS" in response[1])

        request = """GET log
Columns: time current_host_name current_service_description current_host_groups current_service_groups
Filter: time >= """ + str(int(now)) + """
Filter: current_host_name = test_host_0
Filter: current_service_description = test_ok_0
And: 2"""
        good_response = """1234567890;test_host_0;test_ok_0;hostgroup_01,allhosts,up;servicegroup_02,ok,servicegroup_01
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        # remove the timestamps
        good_response = ';'.join(good_response.split(';')[1:])
        response = ';'.join(response.split(';')[1:])
        print response
        self.assert_(self.lines_equal(response, good_response))

    def test_thruk_empty_stats(self):
        self.print_header()
        self.update_broker()
        # surely no host object matches with this filter
        # nonetheless there must be a line of output
        request = """GET hosts
Filter: has_been_checked = 10
Filter: check_type = 10
Stats: sum percent_state_change
Stats: min percent_state_change
Stats: max percent_state_change
OutputFormat: csv"""

        good_response = """0;0;0"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(self.lines_equal(response, good_response))

    def test_thruk_host_parents(self):
        self.print_header()
        self.update_broker()
        # surely no host object matches with this filter
        # nonetheless there must be a line of output
        request = """GET hosts
Columns: host_name parents
OutputFormat: csv"""

        good_response = """test_router_0;
test_host_0;test_router_0
"""

        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(self.lines_equal(response, good_response))

    def test_statsgroupby(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        svc1 = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        print svc1
        self.scheduler_loop(1, [[svc1, 1, 'W']])
        self.update_broker()

        request = """GET services
Filter: contacts >= test_contact
Stats: state != 9999
Stats: state = 0
Stats: state = 1
Stats: state = 2
Stats: state = 3
StatsGroupBy: host_name"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(self.contains_line(response, 'test_host_0;1;0;1;0;0'))

        request = """GET services
Stats: state != 9999
StatsGroupBy: state
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        # does not show null-values
        #self.assert_(self.contains_line(response, '0;0'))
        self.assert_(self.contains_line(response, '1;1'))
        #self.assert_(self.contains_line(response, '2;0'))
        #self.assert_(self.contains_line(response, '3;0'))

    def test_multisite_column_groupby(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        router = self.sched.hosts.find_by_name("test_router_0")
        host = self.sched.hosts.find_by_name("test_host_0")
        svc = self.sched.services.find_srv_by_name_and_hostname("test_host_0", "test_ok_0")
        host.act_depend_of = []
        router.act_depend_of = []
        self.scheduler_loop(4, [[router, 1, 'D'], [host, 1, 'D'], [svc, 1, 'W']])
        self.update_broker()
        self.scheduler_loop(1, [[router, 0, 'U'], [host, 0, 'U'], [svc, 0, 'O']])
        self.update_broker()
        self.scheduler_loop(1, [[router, 1, 'D'], [host, 0, 'U'], [svc, 2, 'C']])
        self.update_broker()

        request = """GET log
Columns: host_name service_description
Filter: log_time >= 1292256802
Filter: class = 1
Stats: state = 0
Stats: state = 1
Stats: state = 2
Stats: state = 3
Stats: state != 0
OutputFormat: csv
Limit: 1001"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print "response=%r" % response
        self.assert_(self.contains_line(response, 'test_host_0;;1;3;0;0;3'))
        self.assert_(self.contains_line(response, 'test_router_0;;1;4;0;0;4'))
        self.assert_(self.contains_line(response, 'test_host_0;test_ok_0;1;2;1;0;3'))
        # does not show null-values
        #self.assert_(self.contains_line(response, '0;0'))
        #self.assert_(self.contains_line(response, '1;1'))
        #self.assert_(self.contains_line(response, '2;0'))
        #self.assert_(self.contains_line(response, '3;0'))

    def test_downtimes_ref(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        duration = 180
        now = time.time()
        cmd = "[%lu] SCHEDULE_SVC_DOWNTIME;test_host_0;test_ok_0;%d;%d;0;0;%d;lausser;blablub" % (now, now, now + duration, duration)
        self.sched.run_external_command(cmd)
        self.update_broker(True)
        request = 'GET downtimes\nColumns: host_name service_description id comment\n'
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(re.search('test_host_0;test_ok_0;[0-9]+;blablub\n', response) is not None)

    def test_display_name(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET hosts
Filter: name = test_host_0
Columns: name display_name"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assertEqual('test_host_0;test_host_0\n', response )
        request = """GET services
Filter: host_name = test_host_0
Filter: description = test_ok_0
Columns: description host_name display_name"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        self.assertEqual('test_ok_0;test_host_0;test_ok_0\n', response )


@mock_livestatus_handle_request
class TestConfigComplex(TestConfig):
    def setUp(self):
        self.setup_with_file('etc/shinken_problem_impact.cfg')
        self.testid = str(os.getpid() + random.randint(1, 1000))
        self.init_livestatus()
        print "Cleaning old broks?"
        self.sched.conf.skip_initial_broks = False
        self.sched.brokers['Default-Broker'] = {'broks' : {}, 'has_full_broks' : False}
        self.sched.fill_initial_broks('Default-Broker')

        self.update_broker()
        self.livestatus_path = None
        self.nagios_config = None
        # add use_aggressive_host_checking so we can mix exit codes 1 and 2
        # but still get DOWN state
        host = self.sched.hosts.find_by_name("test_host_0")
        host.__class__.use_aggressive_host_checking = 1

    #  test_host_0  has parents test_router_0,test_router_1
    def test_thruk_parents(self):
        self.print_header()
        now = time.time()
        objlist = []
        for host in self.sched.hosts:
            objlist.append([host, 0, 'UP'])
        for service in self.sched.services:
            objlist.append([service, 0, 'OK'])
        self.scheduler_loop(1, objlist)
        self.update_broker()
        request = """GET hosts
Columns: host_name parents childs
OutputFormat: csv
"""
        good_response = """test_router_0;;test_host_0,test_host_1
test_router_1;;test_host_0,test_host_1
test_host_0;test_router_0,test_router_1;
test_host_1;test_router_0,test_router_1;
"""
        response, keepalive = self.livestatus_broker.livestatus.handle_request(request)
        print response
        self.assert_(self.lines_equal(response, good_response))


if __name__ == '__main__':
    #import cProfile
    command = """unittest.main()"""
    unittest.main()
    #cProfile.runctx( command, globals(), locals(), filename="/tmp/livestatus.profile" )

    #allsuite = unittest.TestLoader.loadTestsFromModule(TestConfig)
    #unittest.TextTestRunner(verbosity=2).run(allsuite)
