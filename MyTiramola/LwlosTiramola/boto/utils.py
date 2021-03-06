# Copyright (c) 2006-2012 Mitch Garnaat http://garnaat.org/
# Copyright (c) 2010, Eucalyptus Systems, Inc.
# Copyright (c) 2012 Amazon.com, Inc. or its affiliates.
# All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

#
# Parts of this code were copied or derived from sample code supplied by AWS.
# The following notice applies to that code.
#
#  This software code is made available "AS IS" without warranties of any
#  kind.  You may copy, display, modify and redistribute the software
#  code either by itself or as incorporated into your code; provided that
#  you do not remove any proprietary notices.  Your use of this software
#  code is at your own risk and you waive any claim against Amazon
#  Digital Services, Inc. or its affiliates with respect to your use of
#  this software code. (c) 2006 Amazon Digital Services, Inc. or its
#  affiliates.

"""
Some handy utility functions used by several classes.
"""

import socket
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse
import imp
import subprocess
import io
import time
import logging.handlers
import boto
import boto.provider
import tempfile
import smtplib
import datetime
import re
import email.mime.multipart
import email.mime.base
import email.mime.text
import email.utils
import email.encoders
import gzip
import base64
import functools
try:
    from hashlib import md5
except ImportError:
    from md5 import md5


try:
    import hashlib
    _hashfn = hashlib.sha512
except ImportError:
    import md5
    _hashfn = md5.md5

from boto.compat import json

# List of Query String Arguments of Interest
qsa_of_interest = ['acl', 'cors', 'defaultObjectAcl', 'location', 'logging',
                   'partNumber', 'policy', 'requestPayment', 'torrent',
                   'versioning', 'versionId', 'versions', 'website',
                   'uploads', 'uploadId', 'response-content-type',
                   'response-content-language', 'response-expires',
                   'response-cache-control', 'response-content-disposition',
                   'response-content-encoding', 'delete', 'lifecycle',
                   'tagging', 'restore',
                   # storageClass is a QSA for buckets in Google Cloud Storage.
                   # (StorageClass is associated to individual keys in S3, but
                   # having it listed here should cause no problems because
                   # GET bucket?storageClass is not part of the S3 API.)
                   'storageClass',
                   # websiteConfig is a QSA for buckets in Google Cloud Storage.
                   'websiteConfig',
                   # compose is a QSA for objects in Google Cloud Storage.
                   'compose']


_first_cap_regex = re.compile('(.)([A-Z][a-z]+)')
_number_cap_regex = re.compile('([a-z])([0-9]+)')
_end_cap_regex = re.compile('([a-z0-9])([A-Z])')


def unquote_v(nv):
    if len(nv) == 1:
        return nv
    else:
        return (nv[0], urllib.parse.unquote(nv[1]))


def canonical_string(method, path, headers, expires=None,
                     provider=None):
    """
    Generates the aws canonical string for the given parameters
    """
    if not provider:
        provider = boto.provider.get_default()
    interesting_headers = {}
    for key in headers:
        lk = key.lower()
        if headers[key] != None and (lk in ['content-md5', 'content-type', 'date'] or
                                     lk.startswith(provider.header_prefix)):
            interesting_headers[lk] = str(headers[key]).strip()

    # these keys get empty strings if they don't exist
    if 'content-type' not in interesting_headers:
        interesting_headers['content-type'] = ''
    if 'content-md5' not in interesting_headers:
        interesting_headers['content-md5'] = ''

    # just in case someone used this.  it's not necessary in this lib.
    if provider.date_header in interesting_headers:
        interesting_headers['date'] = ''

    # if you're using expires for query string auth, then it trumps date
    # (and provider.date_header)
    if expires:
        interesting_headers['date'] = str(expires)

    sorted_header_keys = sorted(interesting_headers.keys())

    buf = "%s\n" % method
    for key in sorted_header_keys:
        val = interesting_headers[key]
        if key.startswith(provider.header_prefix):
            buf += "%s:%s\n" % (key, val)
        else:
            buf += "%s\n" % val

    # don't include anything after the first ? in the resource...
    # unless it is one of the QSA of interest, defined above
    t = path.split('?')
    buf += t[0]

    if len(t) > 1:
        qsa = t[1].split('&')
        qsa = [a.split('=', 1) for a in qsa]
        qsa = [unquote_v(a) for a in qsa if a[0] in qsa_of_interest]
        if len(qsa) > 0:
            def cmp(a, b):
              return (a > b) - (a < b)
            if hasattr(functools, 'cmp_to_key'):
                qsa.sort(key=functools.cmp_to_key(lambda x, y:cmp(x[0], y[0])))
            else:
                qsa.sort(cmp=lambda x, y:cmp(x[0], y[0]))
            qsa = ['='.join(a) for a in qsa]
            buf += '?'
            buf += '&'.join(qsa)

    return buf


def merge_meta(headers, metadata, provider=None):
    if not provider:
        provider = boto.provider.get_default()
    metadata_prefix = provider.metadata_prefix
    final_headers = headers.copy()
    for k in list(metadata.keys()):
        if k.lower() in ['cache-control', 'content-md5', 'content-type',
                         'content-encoding', 'content-disposition',
                         'expires']:
            final_headers[k] = metadata[k]
        else:
            final_headers[metadata_prefix + k] = metadata[k]

    return final_headers


def get_aws_metadata(headers, provider=None):
    if not provider:
        provider = boto.provider.get_default()
    metadata_prefix = provider.metadata_prefix
    metadata = {}
    for hkey in list(headers.keys()):
        if hkey.lower().startswith(metadata_prefix):
            val = urllib.parse.unquote_plus(headers[hkey])
            if hasattr(val, 'decode'):
              try:
                  metadata[hkey[len(metadata_prefix):]] = val.decode('utf-8')
              except UnicodeDecodeError:
                  metadata[hkey[len(metadata_prefix):]] = val
            else:
              metadata[hkey[len(metadata_prefix):]] = ensure_string(val)
            del headers[hkey]
    return metadata


def retry_url(url, retry_on_404=True, num_retries=10):
    """
    Retry a url.  This is specifically used for accessing the metadata
    service on an instance.  Since this address should never be proxied
    (for security reasons), we create a ProxyHandler with a NULL
    dictionary to override any proxy settings in the environment.
    """
    for i in range(0, num_retries):
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(url)
            r = opener.open(req)
            result = r.read()
            return result
        except urllib.error.HTTPError as e:
            # in 2.6 you use getcode(), in 2.5 and earlier you use code
            if hasattr(e, 'getcode'):
                code = e.getcode()
            else:
                code = e.code
            if code == 404 and not retry_on_404:
                return ''
        except Exception as e:
            pass
        boto.log.exception('Caught exception reading instance data')
        # If not on the last iteration of the loop then sleep.
        if i + 1 != num_retries:
            time.sleep(2 ** i)
    boto.log.error('Unable to read instance data, giving up')
    return ''


def _get_instance_metadata(url, num_retries):
    return LazyLoadMetadata(url, num_retries)


class LazyLoadMetadata(dict):
    def __init__(self, url, num_retries):
        self._url = url
        self._num_retries = num_retries
        self._leaves = {}
        self._dicts = []
        data = boto.utils.retry_url(self._url, num_retries=self._num_retries)
        if data:
            fields = data.split('\n')
            for field in fields:
                if field.endswith('/'):
                    key = field[0:-1]
                    self._dicts.append(key)
                else:
                    p = field.find('=')
                    if p > 0:
                        key = field[p + 1:]
                        resource = field[0:p] + '/openssh-key'
                    else:
                        key = resource = field
                    self._leaves[key] = resource
                self[key] = None

    def _materialize(self):
        for key in self:
            self[key]

    def __getitem__(self, key):
        if key not in self:
            # allow dict to throw the KeyError
            return super(LazyLoadMetadata, self).__getitem__(key)

        # already loaded
        val = super(LazyLoadMetadata, self).__getitem__(key)
        if val is not None:
            return val

        if key in self._leaves:
            resource = self._leaves[key]
            val = boto.utils.retry_url(self._url + urllib.parse.quote(resource,
                                                                safe="/:"),
                                       num_retries=self._num_retries)
            if val and val[0] == '{':
                val = json.loads(val)
            else:
                p = val.find('\n')
                if p > 0:
                    val = val.split('\n')
            self[key] = val
        elif key in self._dicts:
            self[key] = LazyLoadMetadata(self._url + key + '/',
                                         self._num_retries)

        return super(LazyLoadMetadata, self).__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def values(self):
        self._materialize()
        return list(super(LazyLoadMetadata, self).values())

    def items(self):
        self._materialize()
        return list(super(LazyLoadMetadata, self).items())

    def __str__(self):
        self._materialize()
        return super(LazyLoadMetadata, self).__str__()

    def __repr__(self):
        self._materialize()
        return super(LazyLoadMetadata, self).__repr__()


def _build_instance_metadata_url(url, version, path):
    """
    Builds an EC2 metadata URL for fetching information about an instance.

    Requires the following arguments: a URL, a version and a path.

    Example:

        >>> _build_instance_metadata_url('http://169.254.169.254', 'latest', 'meta-data')
        http://169.254.169.254/latest/meta-data/

    """
    return '%s/%s/%s/' % (url, version, path)


def get_instance_metadata(version='latest', url='http://169.254.169.254',
                          data='meta-data', timeout=None, num_retries=5):
    """
    Returns the instance metadata as a nested Python dictionary.
    Simple values (e.g. local_hostname, hostname, etc.) will be
    stored as string values.  Values such as ancestor-ami-ids will
    be stored in the dict as a list of string values.  More complex
    fields such as public-keys and will be stored as nested dicts.

    If the timeout is specified, the connection to the specified url
    will time out after the specified number of seconds.

    """
    if timeout is not None:
        original = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
    try:
        metadata_url = _build_instance_metadata_url(url, version, data)
        return _get_instance_metadata(metadata_url, num_retries=num_retries)
    except urllib.error.URLError as e:
        return None
    finally:
        if timeout is not None:
            socket.setdefaulttimeout(original)


def get_instance_identity(version='latest', url='http://169.254.169.254',
                          timeout=None, num_retries=5):
    """
    Returns the instance identity as a nested Python dictionary.
    """
    iid = {}
    base_url = _build_instance_metadata_url(url, version, 'dynamic/instance-identity')
    if timeout is not None:
        original = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
    try:
        data = retry_url(base_url, num_retries=num_retries)
        fields = data.split('\n')
        for field in fields:
            val = retry_url(base_url + '/' + field + '/')
            if val[0] == '{':
                val = json.loads(val)
            if field:
                iid[field] = val
        return iid
    except urllib.error.URLError as e:
        return None
    finally:
        if timeout is not None:
            socket.setdefaulttimeout(original)


def get_instance_userdata(version='latest', sep=None,
                          url='http://169.254.169.254'):
    ud_url = _build_instance_metadata_url(url, version, 'user-data')
    user_data = retry_url(ud_url, retry_on_404=False)
    if user_data:
        if sep:
            l = user_data.split(sep)
            user_data = {}
            for nvpair in l:
                t = nvpair.split('=')
                user_data[t[0].strip()] = t[1].strip()
    return user_data

ISO8601 = '%Y-%m-%dT%H:%M:%SZ'
ISO8601_MS = '%Y-%m-%dT%H:%M:%S.%fZ'
RFC1123 = '%a, %d %b %Y %H:%M:%S %Z'

def get_ts(ts=None):
    if not ts:
        ts = time.gmtime()
    return time.strftime(ISO8601, ts)


def parse_ts(ts):
    ts = ts.strip()
    try:
        dt = datetime.datetime.strptime(ts, ISO8601)
        return dt
    except ValueError:
        try:
            dt = datetime.datetime.strptime(ts, ISO8601_MS)
            return dt
        except ValueError:
            dt = datetime.datetime.strptime(ts, RFC1123)
            return dt

def find_class(module_name, class_name=None):
    if class_name:
        module_name = "%s.%s" % (module_name, class_name)
    modules = module_name.split('.')
    c = None

    try:
        for m in modules[1:]:
            if c:
                c = getattr(c, m)
            else:
                c = getattr(__import__(".".join(modules[0:-1])), m)
        return c
    except:
        return None


def update_dme(username, password, dme_id, ip_address):
    """
    Update your Dynamic DNS record with DNSMadeEasy.com
    """
    dme_url = 'https://www.dnsmadeeasy.com/servlet/updateip'
    dme_url += '?username=%s&password=%s&id=%s&ip=%s'
    s = urllib.request.urlopen(dme_url % (username, password, dme_id, ip_address))
    return s.read()


def fetch_file(uri, file=None, username=None, password=None):
    """
    Fetch a file based on the URI provided. If you do not pass in a file pointer
    a tempfile.NamedTemporaryFile, or None if the file could not be
    retrieved is returned.
    The URI can be either an HTTP url, or "s3://bucket_name/key_name"
    """
    boto.log.info('Fetching %s' % uri)
    if file == None:
        file = tempfile.NamedTemporaryFile()
    try:
        if uri.startswith('s3://'):
            bucket_name, key_name = uri[len('s3://'):].split('/', 1)
            c = boto.connect_s3(aws_access_key_id=username,
                                aws_secret_access_key=password)
            bucket = c.get_bucket(bucket_name)
            key = bucket.get_key(key_name)
            key.get_contents_to_file(file)
        else:
            if username and password:
                passman = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                passman.add_password(None, uri, username, password)
                authhandler = urllib.request.HTTPBasicAuthHandler(passman)
                opener = urllib.request.build_opener(authhandler)
                urllib.request.install_opener(opener)
            s = urllib.request.urlopen(uri)
            file.write(s.read())
        file.seek(0)
    except:
        raise
        boto.log.exception('Problem Retrieving file: %s' % uri)
        file = None
    return file


class ShellCommand(object):

    def __init__(self, command, wait=True, fail_fast=False, cwd=None):
        self.exit_code = 0
        self.command = command
        self.log_fp = io.StringIO()
        self.wait = wait
        self.fail_fast = fail_fast
        self.run(cwd=cwd)

    def run(self, cwd=None):
        boto.log.info('running:%s' % self.command)
        self.process = subprocess.Popen(self.command, shell=True,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        cwd=cwd)
        if(self.wait):
            while self.process.poll() == None:
                time.sleep(1)
                t = self.process.communicate()
                self.log_fp.write(t[0])
                self.log_fp.write(t[1])
            boto.log.info(self.log_fp.getvalue())
            self.exit_code = self.process.returncode

            if self.fail_fast and self.exit_code != 0:
                raise Exception("Command " + self.command + " failed with status " + self.exit_code)

            return self.exit_code

    def setReadOnly(self, value):
        raise AttributeError

    def getStatus(self):
        return self.exit_code

    status = property(getStatus, setReadOnly, None, 'The exit code for the command')

    def getOutput(self):
        return self.log_fp.getvalue()

    output = property(getOutput, setReadOnly, None, 'The STDIN and STDERR output of the command')


class AuthSMTPHandler(logging.handlers.SMTPHandler):
    """
    This class extends the SMTPHandler in the standard Python logging module
    to accept a username and password on the constructor and to then use those
    credentials to authenticate with the SMTP server.  To use this, you could
    add something like this in your boto config file:

    [handler_hand07]
    class=boto.utils.AuthSMTPHandler
    level=WARN
    formatter=form07
    args=('localhost', 'username', 'password', 'from@abc', ['user1@abc', 'user2@xyz'], 'Logger Subject')
    """

    def __init__(self, mailhost, username, password,
                 fromaddr, toaddrs, subject):
        """
        Initialize the handler.

        We have extended the constructor to accept a username/password
        for SMTP authentication.
        """
        logging.handlers.SMTPHandler.__init__(self, mailhost, fromaddr,
                                              toaddrs, subject)
        self.username = username
        self.password = password

    def emit(self, record):
        """
        Emit a record.

        Format the record and send it to the specified addressees.
        It would be really nice if I could add authorization to this class
        without having to resort to cut and paste inheritance but, no.
        """
        try:
            port = self.mailport
            if not port:
                port = smtplib.SMTP_PORT
            smtp = smtplib.SMTP(self.mailhost, port)
            smtp.login(self.username, self.password)
            msg = self.format(record)
            msg = "From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\n\r\n%s" % (
                            self.fromaddr,
                            ','.join(self.toaddrs),
                            self.getSubject(record),
                            email.utils.formatdate(), msg)
            smtp.sendmail(self.fromaddr, self.toaddrs, msg)
            smtp.quit()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


class LRUCache(dict):
    """A dictionary-like object that stores only a certain number of items, and
    discards its least recently used item when full.

    >>> cache = LRUCache(3)
    >>> cache['A'] = 0
    >>> cache['B'] = 1
    >>> cache['C'] = 2
    >>> len(cache)
    3

    >>> cache['A']
    0

    Adding new items to the cache does not increase its size. Instead, the least
    recently used item is dropped:

    >>> cache['D'] = 3
    >>> len(cache)
    3
    >>> 'B' in cache
    False

    Iterating over the cache returns the keys, starting with the most recently
    used:

    >>> for key in cache:
    ...     print key
    D
    A
    C

    This code is based on the LRUCache class from Genshi which is based on
    `Myghty <http://www.myghty.org>`_'s LRUCache from ``myghtyutils.util``,
    written by Mike Bayer and released under the MIT license (Genshi uses the
    BSD License).
    """

    class _Item(object):
        def __init__(self, key, value):
            self.previous = self.__next__ = None
            self.key = key
            self.value = value

        def __repr__(self):
            return repr(self.value)

    def __init__(self, capacity):
        self._dict = dict()
        self.capacity = capacity
        self.head = None
        self.tail = None

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        cur = self.head
        while cur:
            yield cur.key
            cur = cur.__next__

    def __len__(self):
        return len(self._dict)

    def __getitem__(self, key):
        item = self._dict[key]
        self._update_item(item)
        return item.value

    def __setitem__(self, key, value):
        item = self._dict.get(key)
        if item is None:
            item = self._Item(key, value)
            self._dict[key] = item
            self._insert_item(item)
        else:
            item.value = value
            self._update_item(item)
            self._manage_size()

    def __repr__(self):
        return repr(self._dict)

    def _insert_item(self, item):
        item.previous = None
        item.next = self.head
        if self.head is not None:
            self.head.previous = item
        else:
            self.tail = item
        self.head = item
        self._manage_size()

    def _manage_size(self):
        while len(self._dict) > self.capacity:
            del self._dict[self.tail.key]
            if self.tail != self.head:
                self.tail = self.tail.previous
                self.tail.next = None
            else:
                self.head = self.tail = None

    def _update_item(self, item):
        if self.head == item:
            return

        previous = item.previous
        previous.next = item.__next__
        if item.__next__ is not None:
            item.next.previous = previous
        else:
            self.tail = previous

        item.previous = None
        item.next = self.head
        self.head.previous = self.head = item


class Password(object):
    """
    Password object that stores itself as hashed.
    Hash defaults to SHA512 if available, MD5 otherwise.
    """
    hashfunc = _hashfn

    def __init__(self, str=None, hashfunc=None):
        """
        Load the string from an initial value, this should be the
        raw hashed password.
        """
        self.str = str
        if hashfunc:
           self.hashfunc = hashfunc

    def set(self, value):
        value = ensure_bytes(value)
        self.str = self.hashfunc(value).hexdigest()

    def __str__(self):
        return str(self.str)

    def __eq__(self, other):
        if other == None:
            return False
        other = ensure_bytes(other)
        return str(self.hashfunc(other).hexdigest()) == str(self.str)

    def __len__(self):
        if self.str:
            return len(self.str)
        else:
            return 0


def notify(subject, body=None, html_body=None, to_string=None,
           attachments=None, append_instance_id=True):
    attachments = attachments or []
    if append_instance_id:
        subject = "[%s] %s" % (boto.config.get_value("Instance", "instance-id"), subject)
    if not to_string:
        to_string = boto.config.get_value('Notification', 'smtp_to', None)
    if to_string:
        try:
            from_string = boto.config.get_value('Notification', 'smtp_from', 'boto')
            msg = email.mime.multipart.MIMEMultipart()
            msg['From'] = from_string
            msg['Reply-To'] = from_string
            msg['To'] = to_string
            msg['Date'] = email.utils.formatdate(localtime=True)
            msg['Subject'] = subject

            if body:
                msg.attach(email.mime.text.MIMEText(body))

            if html_body:
                part = email.mime.base.MIMEBase('text', 'html')
                part.set_payload(html_body)
                email.encoders.encode_base64(part)
                msg.attach(part)

            for part in attachments:
                msg.attach(part)

            smtp_host = boto.config.get_value('Notification', 'smtp_host', 'localhost')

            # Alternate port support
            if boto.config.get_value("Notification", "smtp_port"):
                server = smtplib.SMTP(smtp_host, int(boto.config.get_value("Notification", "smtp_port")))
            else:
                server = smtplib.SMTP(smtp_host)

            # TLS support
            if boto.config.getbool("Notification", "smtp_tls"):
                server.ehlo()
                server.starttls()
                server.ehlo()
            smtp_user = boto.config.get_value('Notification', 'smtp_user', '')
            smtp_pass = boto.config.get_value('Notification', 'smtp_pass', '')
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_string, to_string, msg.as_string())
            server.quit()
        except:
            boto.log.exception('notify failed')


def get_utf8_value(value):
    if not isinstance(value, str) and not isinstance(value, str):
        value = str(value)
    if isinstance(value, str):
        return value.encode('utf-8')
    else:
        return value


def mklist(value):
    if not isinstance(value, list):
        if isinstance(value, tuple):
            value = list(value)
        else:
            value = [value]
    return value


def pythonize_name(name):
    """Convert camel case to a "pythonic" name.

    Examples::

        pythonize_name('CamelCase') -> 'camel_case'
        pythonize_name('already_pythonized') -> 'already_pythonized'
        pythonize_name('HTTPRequest') -> 'http_request'
        pythonize_name('HTTPStatus200Ok') -> 'http_status_200_ok'
        pythonize_name('UPPER') -> 'upper'
        pythonize_name('') -> ''

    """
    s1 = _first_cap_regex.sub(r'\1_\2', name)
    s2 = _number_cap_regex.sub(r'\1_\2', s1)
    return _end_cap_regex.sub(r'\1_\2', s2).lower()


def write_mime_multipart(content, compress=False, deftype='text/plain', delimiter=':'):
    """Description:
    :param content: A list of tuples of name-content pairs. This is used
    instead of a dict to ensure that scripts run in order
    :type list of tuples:

    :param compress: Use gzip to compress the scripts, defaults to no compression
    :type bool:

    :param deftype: The type that should be assumed if nothing else can be figured out
    :type str:

    :param delimiter: mime delimiter
    :type str:

    :return: Final mime multipart
    :rtype: str:
    """
    wrapper = email.mime.multipart.MIMEMultipart()
    for name, con in content:
        definite_type = guess_mime_type(con, deftype)
        maintype, subtype = definite_type.split('/', 1)
        if maintype == 'text':
            mime_con = email.mime.text.MIMEText(con, _subtype=subtype)
        else:
            mime_con = email.mime.base.MIMEBase(maintype, subtype)
            mime_con.set_payload(con)
            # Encode the payload using Base64
            email.encoders.encode_base64(mime_con)
        mime_con.add_header('Content-Disposition', 'attachment', filename=name)
        wrapper.attach(mime_con)
    rcontent = wrapper.as_string()

    if compress:
        buf = io.StringIO()
        gz = gzip.GzipFile(mode='wb', fileobj=buf)
        try:
            gz.write(rcontent)
        finally:
            gz.close()
        rcontent = buf.getvalue()

    return rcontent


def guess_mime_type(content, deftype):
    """Description: Guess the mime type of a block of text
    :param content: content we're finding the type of
    :type str:

    :param deftype: Default mime type
    :type str:

    :rtype: <type>:
    :return: <description>
    """
    #Mappings recognized by cloudinit
    starts_with_mappings = {
        '#include': 'text/x-include-url',
        '#!': 'text/x-shellscript',
        '#cloud-config': 'text/cloud-config',
        '#upstart-job': 'text/upstart-job',
        '#part-handler': 'text/part-handler',
        '#cloud-boothook': 'text/cloud-boothook'
    }
    rtype = deftype
    for possible_type, mimetype in list(starts_with_mappings.items()):
        if content.startswith(possible_type):
            rtype = mimetype
            break
    return(rtype)


def compute_md5(fp, buf_size=8192, size=None):
    """
    Compute MD5 hash on passed file and return results in a tuple of values.

    :type fp: file
    :param fp: File pointer to the file to MD5 hash.  The file pointer
               will be reset to its current location before the
               method returns.

    :type buf_size: integer
    :param buf_size: Number of bytes per read request.

    :type size: int
    :param size: (optional) The Maximum number of bytes to read from
                 the file pointer (fp). This is useful when uploading
                 a file in multiple parts where the file is being
                 split inplace into different parts. Less bytes may
                 be available.

    :rtype: tuple
    :return: A tuple containing the hex digest version of the MD5 hash
             as the first element, the base64 encoded version of the
             plain digest as the second element and the data size as
             the third element.
    """
    return compute_hash(fp, buf_size, size, hash_algorithm=md5)


def compute_hash(fp, buf_size=8192, size=None, hash_algorithm=md5):
    hash_obj = hash_algorithm()
    spos = fp.tell()
    if size and size < buf_size:
        s = fp.read(size)
    else:
        s = fp.read(buf_size)
    while s:
        hash_obj.update(s)
        if size:
            size -= len(s)
            if size <= 0:
                break
        if size and size < buf_size:
            s = fp.read(size)
        else:
            s = fp.read(buf_size)
    hex_digest = hash_obj.hexdigest()
    base64_digest = base64.encodestring(hash_obj.digest())
    if base64_digest[-1] == '\n':
        base64_digest = base64_digest[0:-1]
    # data_size based on bytes read.
    data_size = fp.tell() - spos
    fp.seek(spos)
    return (hex_digest, base64_digest, data_size)

def ensure_bytes(string):
    # in python2 convert unicode strings to regular strings and in
    # python3 convert strings to bytes, but don't waste time converting
    # regular python2 strings to themselves
    if not isinstance(string, str) and hasattr(string, 'encode'):
        # python2 unicode string
        string = string.encode('utf-8')
    elif isinstance(string, str) and not hasattr(string, 'decode'):
        # python3 string -> bytes
        string = string.encode('utf-8')
    return string

def ensure_string(string):
    if hasattr(string, 'decode') and not hasattr(string, 'encode'):
        # it's a python3 byte literal
        string = string.decode('utf-8')
    return string

class FakeHashObj(object):
  """Intercept calls to hashlib objects and ensure
  only bytes get by in python3
  """
  def __init__(self, obj):
    self.obj = obj

  def __getattr__(self, attr):
    return getattr(self.obj, attr)

  def update(self, str):
    return self.obj.update(boto.utils.ensure_bytes(str))

def wrap_hash_function(hf):
  def get_hash(*args, **kwargs):
    if args:
      args = list(args)
      args[0] = boto.utils.ensure_bytes(args[0])
    obj = FakeHashObj(hf(*args, **kwargs))
    return obj
  return get_hash

def find_matching_headers(name, headers):
    """
    Takes a specific header name and a dict of headers {"name": "value"}.
    Returns a list of matching header names, case-insensitive.

    """
    return [h for h in headers if h.lower() == name.lower()]


def merge_headers_by_name(name, headers):
    """
    Takes a specific header name and a dict of headers {"name": "value"}.
    Returns a string of all header values, comma-separated, that match the
    input header name, case-insensitive.

    """
    matching_headers = find_matching_headers(name, headers)
    return ','.join(str(headers[h]) for h in matching_headers
                    if headers[h] is not None)
