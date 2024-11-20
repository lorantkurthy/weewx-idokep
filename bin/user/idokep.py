# Copyright 2014 Lorant Kurthy
# 
#==============================================================================
# Upload data to Idokep Pro
#==============================================================================
# https://pro.idokep.hu
#
# To enable this module, put this file in bin/user, add the following to
# weewx.conf, then restart weewx.
#
# [StdRESTful]
#     [[IDOKEP]]
#         username = your IDOKEP username
#         password = your IDOKEP password
#         log_success = True
#         log_failure = True
#         skip_upload = False
#         station_type = WS23XX
#
# [Engine]
#     [[Services]]
#          restful_services = , user.idokep.IDOKEP
#

import queue
import sys
import syslog
import time
import urllib.parse
import urllib.request

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, accumulateLeaves
import weewx.manager

#==============================================================================
# IDOKEP
#==============================================================================

class IDOKEP(weewx.restx.StdRESTful):
    """Upload data to IDOKEP
    https://pro.idokep.hu

    URL=https://pro.idokep.hu/sendws.php?
    PARAMETERS:
        user=username
        pass=password
        hom=$v{To} // Temperature outdoor (%.1f C)
        rh=$v{RHo} // Relative humidity outdoor (%d C)
        szelirany=$v{DIR0} // Wind direction (%.0f)
        szelero=$v{WS} // (%.1f m/s)
        p=$v{RP} // Relative pressure (%.1f hPa)
        csap=$v{R24h} // Rain 24h (%.1f mm)
        csap1h=$v{R1h} //Rain 1h (%.1f mm)
        ev=$year
        ho=$mon
        nap=$mday
        ora=$hour
        perc=$min
        mp=$sec
        tipus=WS23xx
    """

    def __init__(self, engine, config_dict):
        super(IDOKEP, self).__init__(engine, config_dict)
        try:
            # Load config data
            site_config = config_dict['StdRESTful']['IDOKEP']
            site_dict = accumulateLeaves(site_config, max_level=1)

            # Check availability of the necessary keys
            if 'username' not in site_dict or 'password' not in site_dict:
                raise KeyError('username or password')
        except KeyError as e:
            syslog.syslog(syslog.LOG_DEBUG, "restx: IDOKEP: "
                          "Data will not be posted: Missing option %s" % e)
            return

        # Set up defaults
        site_dict.setdefault('station_type', 'WS23XX')
        site_dict.setdefault('log_success', True)
        site_dict.setdefault('log_failure', True)
        site_dict.setdefault('skip_upload', False)
        site_dict.setdefault('post_interval', 300)
        site_dict.setdefault('max_backlog', sys.maxsize)
        site_dict.setdefault('stale', None)
        site_dict.setdefault('timeout', 60)
        site_dict.setdefault('max_tries', 3)
        site_dict.setdefault('retry_wait', 5)

        # Initialize and start processing thread
        self.archive_queue = queue.Queue()
        self.archive_thread = IDOKEPThread(
            self.archive_queue,
            username=site_dict['username'],
            password=site_dict['password'],
            station_type=site_dict.get('station_type', 'WS23XX'),
            server_url=site_dict.get('server_url', 'https://pro.idokep.hu/sendws.php'),
            skip_upload=site_dict.get('skip_upload', False),
            post_interval=site_dict.get('post_interval', 300),
            max_backlog=site_dict.get('max_backlog', sys.maxsize),
            stale=site_dict.get('stale', None),
            log_success=site_dict.get('log_success', True),
            log_failure=site_dict.get('log_failure', True),
            timeout=site_dict.get('timeout', 60),
            max_tries=site_dict.get('max_tries', 3),
            retry_wait=site_dict.get('retry_wait', 5)
        )
        self.archive_thread.start()
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        syslog.syslog(syslog.LOG_INFO, "restx: IDOKEP: "
                      "Data will be uploaded for user %s" %
                      site_dict['username'])

    def new_archive_record(self, event):
        self.archive_queue.put(event.record)

class IDOKEPThread(weewx.restx.RESTThread):

    _SERVER_URL = 'https://pro.idokep.hu/sendws.php'
    _FORMATS = {
        'barometer'   : '%.1f',
        'outTemp'     : '%.1f',
        'outHumidity' : '%.0f',
        'windSpeed'   : '%.1f',
        'windDir'     : '%.0f',
        'rain'        : '%.2f',
        'rainRate'    : '%.2f'
    }

    def __init__(self, queue, username, password,
                 station_type='WS23XX', server_url=_SERVER_URL, skip_upload=False,
                 post_interval=300, max_backlog=sys.maxsize, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5):

        """Initialize an instance of IDOKEPThread.
        Required parameters:

        username: IDOKEP username
        password: IDOKEP password
        Please visit https://pro.idokep.hu to sign up and register your station in advance. Max password length for the station: 20. 

        Optional parameters:

        station_type: weather station type
        server_url: https://pro.idokep.hu/sendws.php
        Default is the IDOKEP server

        log_success: If True, log a successful post in the system log.
        Default is True.

        log_failure: If True, log an unsuccessful post in the system log.
        Default is True.

        max_backlog: How many records are allowed to accumulate in the queue
        before the queue is trimmed.
        Default is sys.maxsize (allow any number).

        max_tries: How many times to try the post before giving up.
        Default is 3

        stale: How old a record can be and still considered useful.
        Default is None (never becomes too old).

        post_interval: The interval in seconds between posts.
        IDOKEP requests that uploads happen no more often than 5 minutes, so
        this should be set to no less than 300.
        Default is 300

        timeout: How long to wait for the server to respond before giving up.
        Default is 60 seconds

        skip_upload: debugging option to display data but do not upload
        Default is False
        """
        super(IDOKEPThread, self).__init__(
            queue,
            protocol_name='IDOKEP',
            post_interval=post_interval,
            max_backlog=max_backlog,
            stale=stale,
            log_success=log_success,
            log_failure=log_failure,
            timeout=timeout,
            max_tries=max_tries,
            retry_wait=retry_wait
        )
        self.username = username
        self.password = password
        self.station_type = station_type
        self.server_url = server_url
        self.skip_upload = to_bool(skip_upload)

    def get_record(self, record, archive):
        # Get the record from the superclass
        r = super(IDOKEPThread, self).get_record(record, archive)
        return r

    def process_record(self, record, archive):
        r = self.get_record(record, archive)
        url = self.get_url(r)
        if self.skip_upload:
            syslog.syslog(syslog.LOG_DEBUG, "restx: IDOKEP: skipping upload")
            return
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "weewx/%s" % weewx.__version__)
        self.post_with_retries(req)

    def check_response(self, response):
        error = True
        for line in response:

        # Decode the bytes response to string
            if isinstance(line, bytes):
                line = line.decode('latin-1')

            if 'Feltoltes sikeres' in line:
                error = False

        if error:
            syslog.syslog(syslog.LOG_DEBUG, "restx: IDOKEP: Server response: %s" % ', '.join(decoded_response))
            raise weewx.restx.FailedPost("server returned '%s'" % ', '.join(decoded_response))

    def get_url(self, in_record):
        # Convert to units required by idokep
        record = weewx.units.to_METRICWX(in_record)

        # assemble an array of values in the proper order

        values = [
            "user={}".format(urllib.parse.quote_plus(self.username)),
            "pass={}".format(urllib.parse.quote_plus(self.password))
        ]
        time_tt = time.localtime(record['dateTime'])
        values.extend([
            "ev={}".format(time.strftime("%Y", time_tt)),
            "ho={}".format(time.strftime("%m", time_tt)),
            "nap={}".format(time.strftime("%d", time_tt)),
            "ora={}".format(time.strftime("%H", time_tt)),
            "perc={}".format(time.strftime("%M", time_tt)),
            "mp={}".format(time.strftime("%S", time_tt)),
            "hom={}".format(self._format(record, 'outTemp')),  # C
            "rh={}".format(self._format(record, 'outHumidity')),  # %
            "szelirany={}".format(self._format(record, 'windDir')),
            "szelero={}".format(self._format(record, 'windSpeed')),  # m/s
            "szellokes={}".format(self._format(record, 'windGust')),  # m/s
            "p={}".format(self._format(record, 'barometer')),  # hPa
            "csap={}".format(self._format(record, 'rain')),  # mm
            "csap1h={}".format(self._format(record, 'rainRate')),  # mm
            "tipus={}".format(urllib.parse.quote_plus(self.station_type))
        ])

        valstr = '&'.join(values)
        url = self.server_url + '?' + valstr
        syslog.syslog(syslog.LOG_DEBUG, 'restx: IDOKEP: url: %s' % url)
        return url

    def _format(self, record, label):
        if label in record and record[label] is not None:
            if label in self._FORMATS:
                return self._FORMATS[label] % record[label]
            return str(record[label])
        return ''
