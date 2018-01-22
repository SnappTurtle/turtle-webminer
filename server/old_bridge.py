#!/usr/bin/python

import sys
import json
import datetime
import os

LOG_FILENAME = "debug.log"
LOG_FILE = open(LOG_FILENAME, "a")
INSTANCE_ID = os.urandom(4).encode("hex")

def readline(strip_newline=True):
    data = sys.stdin.readline()
    if strip_newline:
        return data.strip()
    return data

def get_json():
    data = readline()
    try:
        return json.loads(data)
    except:
        debug("Error decoding: %s" % data)
        return False

def sendline(data):
    sys.stdout.write(data.replace("\n", "") + "\n")
    sys.stdout.flush()

def debug(data, term="\n"):
    timestamp = datetime.datetime.now().isoformat()
    line = "[%s:%s]: %s" % (INSTANCE_ID, timestamp, data)
    LOG_FILE.write(line + term)
    LOG_FILE.flush()

class PoolBridge:

    def __init__(self):
        login = None
        password = None
        pool = None

    def dispatch_handler(self, json_data):
        if 'identifier' not in json_data:
            return False

        identifier = json_data['identifier']
        result = False
        if identifier == "handshake":
            result = self._handler_handshake(json_data)
        elif identifier == "solved":
            result = self._handler_solved(json_data)

        return result

    def _handler_handshake(self, json_data):
        pass

    def _handler_solved(self, json_data):
        pass

    def run(self):
        handshake = get_json()
        debug(handshake)
        sendline("FART")

def main():
    poolbridge = PoolBridge()
    poolbridge.run()

if __name__ == "__main__":
    main()
