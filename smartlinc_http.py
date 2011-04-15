
import base64
import getopt
import httplib
import logging
import re
import socket
import sys
import time


# http://insteon1/hrall.htm?1301=I=0
#
# arguments:
#
# 1301=I=0   - turn off devices in scene 1
# 1101=I=0   - turn on devices in scene 1
#
#  About slow access from Linux:
#  http://wiki.smarthome.com/index.php?title=Talk:SmartLinc_Troubleshooting_/_FAQ
#  (see question and link at the bottom of this page)
#  http://www.mvlug.org/JoePfeiffer/SlowGetWithSmartLinc
#  Need to send http reqest in two packets, first packet should carry exactly
#  one character.

class SmartLincHttp:

    def __init__(self, address):
        """Constructor.

        Args:
          address: string, address:port notation
        """
        self.address = address
        self.error_counter = 0

    def runQueryRawSocket(self, url):
        try:
            logging.debug('Smartlinc query: %s' % url)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.sock.connect((self.address, 80))
            self.sock.send('G', socket.MSG_DONTWAIT)
            self.sock.send('ET %s HTTP/1.0\r\n' % url, socket.MSG_DONTWAIT)
            self.sock.send('Authorization: Basic aW5zdGVvbjpQMHczcjJwcGw=\r\n',
                           socket.MSG_DONTWAIT)
            self.sock.send('\r\n', socket.MSG_DONTWAIT)

            self.sock.shutdown(socket.SHUT_WR)
            # logging.debug('Data sent, receiving')

            data = self.sock.recv(1024)
            self.sock.close()
            self.sock = None

            resp_status = None
            resp_data = []
            start_collecting_data = False
            for l in data.split('\n'):
                line = l.strip()
                la = line.split()

                if start_collecting_data:
                    resp_data.append(line)
                    continue

                if len(la) == 3 and la[0] == 'HTTP/1.1':
                    resp_status = int(la[1])
                    continue

                if resp_status and line:
                    continue

                if not line:
                    start_collecting_data = True

            logging.debug('Server response: %s' % resp_data)
            return '\n'.join(resp_data)
        except socket.error:
            self.error_counter += 1
            return None

    def runQuery(self, url):
        try:
            params = {}
            headers = {'Host': self.address,
                       'Connection': 'close',
                       'Authorization': 'Basic aW5zdGVvbjpQMHczcjJwc',
                       }
            logging.debug('Smartlinc query: %s' % url)
            conn = httplib.HTTPConnection(self.address)
            conn.request('GET', url, params, headers)
            resp = conn.getresponse()
            logging.debug('Smartlinc response: %d' % resp.status)
            if resp.status == 200:
                data = resp.read()
                conn.close()
                logging.debug('Smartlinc response data: %s' % data)
                return data
            else:
                logging.error('HTTP Error: %s %s' %
                                    (resp.status,resp.reason))
                self.error_counter += 1
                return None
        except httplib.HTTPException, e:
            logging.error('HTTP error: %s' % e)
            self.error_counter += 1
            return None

    def readCommBuffer(self):
        """Read communication buffer from the controller"""
        data = self.runQueryRawSocket('/buffstatus.xml')
        # this returns something like this:
        # <response><BS>026211F0040F190006025011F004151CAC2B0100</BS></response>
        buf = re.compile('<response><BS>(.*)</BS></response>')
        m = buf.match(data)
        if m:
            return m.group(1)

    def sendCommand(self, cmd_url):
        """Sends command encoded in url, checks status and resends if needed

        returns server reply
        """
        logging.debug('Sending command "%s" to smartlinc controller' % cmd_url)
        while True:
            data = self.runQueryRawSocket(cmd_url)
            comm_buf = self.readCommBuffer()
            if comm_buf and comm_buf.endswith('15'):
                # "send again"
                continue
            else:
                return data

    def _readDeviceStatusInternal(self, addr):
        """Send request, read and parse communication buffer.

        Returns:
          a tuple (comm buffer, status)
        """
        address = addr.upper()
        self.sendCommand('/3?0262%6s0F1900=I=3' % address)

        # read status until internal time changes in the controller to
        # give insteon module time to respond their web app does this.
        old_stat = self.runQueryRawSocket('/status.xml')
        new_stat = old_stat
        while new_stat == old_stat:
            time.sleep(1)
            new_stat = self.runQueryRawSocket('/status.xml')

        data = str(self.readCommBuffer())
        d = re.compile('0262|0250')
        frames = re.split(d, data)
        # each frame must start with device address
        for frame in frames:
            if not frame:
                continue
            # command echo looks like this: '11F0040F190006' (status command)
            # or '11F004151CAC2B13FF' (turn off command)
            # status reply looks like this: '11F004151CAC2B0100'
            # looks like it can be '11F004151CAC2B0000' (0 instead of 1)
            # we are looking for the reply 
            if frame.startswith('%6s151CAC2B01' % address) or frame.startswith('%6s151CAC2B00' % address):
                return (data, frame [-2:])

        return (data, None)

    def readDeviceStatus(self, addr):
        """Request status (on/off) of the device with given address"""
        status = None
        while status is None:
            (comm_buff, status) = self._readDeviceStatusInternal(addr)
            if status is None:
                if comm_buff[-2:] == 'FF':
                    # status ending with 'FF' means "try again"
                    continue
                logging.error('Could not find device status frame in the reply')
                logging.error('Communication buffer returned: "%s"' % comm_buff)
        return int(status, 16)

    def deviceOnOff(self, dev_addr, onoff):
        """Turn device on/off using its direct address

        Notes: see some hints about commands here:
        http://www.smarthome.com/forum/topic.asp?TOPIC_ID=5798
        """
        if onoff:
            cmd = 11
        else:
            cmd = 13
        self.sendCommand('/3?0262%6s0F%02dFF=I=3' % (dev_addr, cmd))


def usage():
    print 'smartlinc_http.py address 0|1'
    sys.exit(0)

def main(args):

    try:
        addr = sys.argv[1]
        cmd = sys.argv[2]
    except IndexError:
        usage()

    sl = SmartLincHttp('10.3.14.14')
    print sl.readDeviceStatus(addr)
    sl.deviceOnOff(addr, int(cmd))
    print sl.readDeviceStatus(addr)


if __name__ == '__main__':
    log_format = '%(asctime)s %(filename)s:%(lineno)d %(levelname)s %(message)s'
    logging.basicConfig(level=logging.DEBUG, format=log_format)

    sys.exit( main(sys.argv) )
