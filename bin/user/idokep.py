# Copyright 2014 Lorant Kurthy

#==============================================================================
# WeatherBug
#==============================================================================
# Upload data to Idokep
# http://www.idokep.hu
#
# To enable this module, put this file in bin/user, add the following to
# weewx.conf, then restart weewx.
#
# [[IDOKEP]]
#     username = your IDOKEP username
#     password = your IDOKEP password
#     log_success = True
#     log_failure = True
#     skip_upload = False
#     station_type = WS23XX

import Queue
import sys
import syslog
import time
import urllib
import urllib2

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool

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
            site_dict = weewx.restx.get_dict(config_dict, 'IDOKEP')
            site_dict['username']
            site_dict['password']
        except KeyError, e:
            syslog.syslog(syslog.LOG_DEBUG, "restx: IDOKEP: "
                          "Data will not be posted: Missing option %s" % e)
            return
        site_dict.setdefault('station_type', 'WS23XX')
        site_dict.setdefault('database_dict', config_dict['Databases'][config_dict['StdArchive']['archive_database']])

        self.archive_queue = Queue.Queue()
        self.archive_thread = IDOKEPThread(self.archive_queue, **site_dict)
        self.archive_thread.start()
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        syslog.syslog(syslog.LOG_INFO, "restx: IDOKEP: "
                      "Data will be uploaded for user %s" %
                      site_dict['username'])

    def new_archive_record(self, event):
        self.archive_queue.put(event.record)

class IDOKEPThread(weewx.restx.RESTThread):

    _SERVER_URL = 'https://pro.idokep.hu/sendws.php'
    _FORMATS = {'barometer'   : '%.1f',
                'outTemp'     : '%.1f',
                'outHumidity' : '%.0f',
                'windSpeed'   : '%.1f',
                'windDir'     : '%.0f',
                'hourRain'    : '%.2f',
                'dayRain'     : '%.2f'}

    def __init__(self, queue, username, password,
                 database_dict,
                 station_type='WS23XX', server_url=_SERVER_URL, skip_upload=False,
                 post_interval=300, max_backlog=sys.maxint, stale=None,
                 log_success=True, log_failure=True, 
                 timeout=60, max_tries=3, retry_wait=5):
        """Initialize an instances of IDOKEPThread.

        Required parameters:

        username: IDOKEP user name

        password: IDOKEP password

        station_type: weather station type

        Optional parameters:
        
        server_url: URL of the server
        Default is the AWEKAS site
        
        log_success: If True, log a successful post in the system log.
        Default is True.

        log_failure: If True, log an unsuccessful post in the system log.
        Default is True.

        max_backlog: How many records are allowed to accumulate in the queue
        before the queue is trimmed.
        Default is sys.maxint (essentially, allow any number).

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
        super(IDOKEPThread, self).__init__(queue,
                                           protocol_name='IDOKEP',
                                           database_dict=database_dict,
                                           post_interval=post_interval,
                                           max_backlog=max_backlog,
                                           stale=stale,
                                           log_success=log_success,
                                           log_failure=log_failure,
                                           timeout=timeout,
                                           max_tries=max_tries,
                                           retry_wait=retry_wait)
        self.username = username
        self.password = password
        self.station_type = station_type
        self.server_url = server_url
        self.skip_upload = to_bool(skip_upload)

    def get_record(self, record, archive):
        # Get the record from my superclass
        r = super(IDOKEPThread, self).get_record(record, archive)
        return r

    def process_record(self, record, archive):
        r = self.get_record(record, archive)
        url = self.get_url(r)
        if self.skip_upload:
            syslog.syslog(syslog.LOG_DEBUG, "restx: IDOKEP: skipping upload")
            return
        req = urllib2.Request(url)
        req.add_header("User-Agent", "weewx/%s" % weewx.__version__)
        self.post_with_retries(req)

    def check_response(self, response):
        error = True
        for line in response:
            if line.find('sz!'):
                error=False

        if error:
            raise weewx.restx.FailedPost("server returned '%s'" % ', '.join(response))

    def get_url(self, in_record):

        # Convert to units required by idokep
        record = weewx.units.to_METRICWX(in_record)

        # assemble an array of values in the proper order
        values = ["{0}={1}".format("user",self.username)]
        values.append("{0}={1}".format("pass",self.password))
        time_tt = time.localtime(record['dateTime'])
        values.append("{0}={1}".format("ev",time.strftime("%Y", time_tt)))
        values.append("{0}={1}".format("ho",time.strftime("%m", time_tt)))
        values.append("{0}={1}".format("nap",time.strftime("%d", time_tt)))
        values.append("{0}={1}".format("ora",time.strftime("%H", time_tt)))
        values.append("{0}={1}".format("perc",time.strftime("%M", time_tt)))
        values.append("{0}={1}".format("mp",time.strftime("%S", time_tt)))
        values.append("{0}={1}".format("hom",self._format(record, 'outTemp'))) # C
        values.append("{0}={1}".format("rh",self._format(record, 'outHumidity'))) # %
        values.append("{0}={1}".format("szelirany",self._format(record, 'windDir')))
        values.append("{0}={1}".format("szelero",self._format(record, 'windSpeed'))) # m/s
        values.append("{0}={1}".format("szellokes",self._format(record, 'windGust'))) # m/s
        values.append("{0}={1}".format("p",self._format(record, 'barometer'))) # hPa
        values.append("{0}={1}".format("csap",self._format(record, 'rain24'))) # mm
        values.append("{0}={1}".format("csap1h",self._format(record, 'hourRain'))) # mm
        values.append("{0}={1}".format("tipus",self.station_type))

        valstr = '&'.join(values)
        url = self.server_url + '?' + valstr
        syslog.syslog(syslog.LOG_DEBUG, 'restx: IDOKEP: url: %s' % url)
        return url

    def _format(self, record, label):
        if record.has_key(label) and record[label] is not None:
            if self._FORMATS.has_key(label):
                return self._FORMATS[label] % record[label]
            return str(record[label])
        return ''
