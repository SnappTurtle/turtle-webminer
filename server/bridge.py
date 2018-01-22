#!/usr/bin/python

from autobahn.twisted.websocket import WebSocketServerProtocol, \
    WebSocketServerFactory

import json
import sys
import uuid
import string

from twisted.python import log
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.protocol import ClientCreator
from twisted.protocols.basic import LineReceiver

HOSTNAME = "127.0.0.1"
PORT = 8181

class StratumClient(LineReceiver):

    delimiter = "\n"
    bridge = None

    def prn(self, data):
        if self.bridge is not None:
            self.bridge.prn(data)
        else:
            print(data)

    def connectionMade(self):
        pass

    def lineReceived(self, line):
        self.prn("Received from pool: %s" % line)
        if self.bridge is None:
            self.prn("Error: Bridge to websocket is not set.")
            return
        self.bridge.pool_process_line(line)

    def terminate(self):
        self.transport.loseConnection()

class Job:

    def __init__(self, job_id, blob, target):
        self.job_id = job_id
        self.blob = blob
        self.target = target

    def get_blob_raw(self):
        return self.blob.decode("hex")

    def get_target_num(self):
        return int(self.target, 16)

class BridgeProtocol(WebSocketServerProtocol):

    def __init__(self):
        super(BridgeProtocol, self).__init__()
        self.instance = str(uuid.uuid4())
        self.pool_address = None
        self.pool_port = None
        self.username = None
        self.password = None
        self.stratum = None
        self.message_id = 0
        self.pool_id = None
        self.jobs = []

    # Pool Side Connection
    def pool_got_connection(self, stratum):
        self.stratum = stratum
        self.stratum.bridge = self
        self.prn(
            "Connected to pool. (Address: '%s:%d', Username: '%s', Password: '%s')"
                % (self.pool_address, self.pool_port, self.username,
                   self.password))
        self.pool_login()

    def pool_process_line(self, line):
        try:
            json_data = json.loads(line)
        except:
            self.shutdown_with_error("Invalid JSON response from pool. " +
                    "Shutting down.")
            return

        if 'jsonrpc' not in json_data and json_data['jsonrpc'] != '2.0':
            self.shutdown_with_error("Invalid JSON RPC version from pool.")
            return

        # If it is a method, we handle it separately
        if 'method' in json_data:
            if 'params' not in json_data:
                # Can't have methods without parameters
                self.shutdown_with_error("Missing parameters in method from " +
                                         "pool.")
                return
            if json_data['params'] is None:
                self.shutdown_with_error("Parameters cannot be null from " +
                                         "pool.")
                return
            method_name = json_data['method']
            params = json_data['params']
            self.pool_handle_method(method_name, params)
            return

        # Not a method so this should be a result
        if 'error' not in json_data:
            self.shutdown_with_error("Missing protocol parameter: 'error'.")
            return

        if json_data['error'] is not None:
            error_msg = "Error"
            error = json_data['error']
            if 'message' in error:
                error_msg = error['message']
            self.send_error_msg("Received error from pool: '%s'." % error_msg)
            return

        # Since there is no error, there must be a result field
        if 'result' not in json_data:
            self.shutdown_with_error("Missing protocol parameter: 'result'.")
            return

        if json_data['result'] is None:
            self.shutdown_with_error("Missing result data.")

        # Handle the result separately
        result = json_data['result']
        self.pool_handle_result(result)

    def pool_handle_method(self, method_name, params):
        if method_name == "job":
            job = self.parse_job(params)
            if job is not None:
                self.jobs.append(job)
                self.announce_job(job)
            else:
                self.send_error_msg("Invalid job data.")
                return
        else:
            self.shutdown_with_error("Unknown method from pool.")

    def pool_handle_result(self, result):
        # Handle the login scenario
        if "id" in result:
            if 'job' not in result:
                self.send_error_msg("Missing job in login from pool.")
                return
            self.pool_id = result['id']
            job = self.parse_job(result['job'])
            if job is not None:
                self.jobs.append(job)
                self.announce_job(job)
            else:
                self.send_error_msg("Invalid job data.")
                return
        # Handle the successful share submission
        else:
            self.announce_share()

    def pool_login(self):
        login_structure = {
                "login": self.username,
                "pass": self.password,
                "agent": "SnappTurtle Web Miner"
                }
        self.pool_send("login", login_structure)

    def pool_send(self, method, params):
        self.message_id += 1
        structure = {
                "id": self.message_id,
                "jsonrpc": "2.0",
                "method": method,
                "params": params
                }
        json_data = json.dumps(structure)
        self.prn("Sent to pool: %s" % json_data)
        self.stratum.sendLine(json_data)

    def pool_relay_solution(self, job_id, nonce, result):
        self.prn("Relaying solution to pool: %s, %s, %s" % (job_id, nonce,
            result))
        params = {
                "id": self.pool_id,
                "job_id": job_id,
                "nonce": nonce,
                "result": result
                }
        self.pool_send("submit", params)

    # Pool Utility
    def parse_job(self, job_data):
        if 'blob' not in job_data:
            return None
        if 'job_id' not in job_data:
            return None
        if 'target' not in job_data:
            return None

        blob = job_data['blob']
        if blob is None or not all(c in string.hexdigits for c in blob):
            return None

        job_id = job_data['job_id']
        if job_id is None:
            return None

        target = job_data['target']
        if target is None or not all(c in string.hexdigits for c in target):
            return None

        return Job(job_id, blob, target)

    # Websocket Utility
    def json_msg(self, identifier, kvs):
        structure = {}
        for i, v in kvs.iteritems():
            structure[i] = v
        structure['identifier'] = identifier
        data = json.dumps(structure)
        return data

    def error_msg(self, message):
        identifier = "error"
        kvs = {"param": message}
        return self.json_msg(identifier, kvs)

    def job_msg(self, job):
        identifier = "job"
        kvs = {
                "blob": job.blob,
                "job_id": job.job_id,
                "target": job.target
                }
        return self.json_msg(identifier, kvs)

    def share_msg(self):
        identifier = 'hashsolved'
        return self.json_msg(identifier, {})

    def prn(self, data):
        print("[%s] %s" % (self.instance, data))

    # Websocket Side Connection
    def onConnect(self, request):
        self.prn("Client connecting: {0}".format(request.peer))

    def onOpen(self):
        self.prn("WebSocket connection open.")

    def send(self, message):
        self.prn("Sent to WebSocket: %s" % message)
        self.sendMessage(message, False)

    def send_error_msg(self, message):
        self.send(self.error_msg(message))

    def shutdown_with_error(self, message):
        self.send_error_msg(message)
        self.shutdown()

    def announce_job(self, job):
        self.send(self.job_msg(job))

    def announce_share(self):
        self.send(self.share_msg())

    def handle_handshake(self, decoded):
        if 'login' not in decoded:
            self.send_error_msg("No login specified")
            return
        self.username = decoded['login']

        if 'password' not in decoded:
            self.send_error_msg("No password specified")
            return
        self.password = decoded['password']

        if 'pool' not in decoded:
            self.send_error_msg("No pool specified")
            return
        pool = decoded['pool']
        try:
            self.pool_address, port_str = pool.split(":")
            self.pool_port = int(port_str)
        except:
            self.send_error_msg("Error when parsing pool information")
            return

        self.prn("Opening bridge to %s:%d" % (self.pool_address,
            self.pool_port))

        c = ClientCreator(reactor, StratumClient)
        d = c.connectTCP(self.pool_address, self.pool_port)
        d.addCallback(self.pool_got_connection)

    def handle_solved(self, decoded):
        if 'job_id' not in decoded or decoded['job_id'] is None:
            self.send_error_msg("Missing job_id in solution.")
            return

        if 'nonce' not in decoded or decoded['nonce'] is None:
            self.send_error_msg("Missing nonce in solution.")
            return

        if 'result' not in decoded or decoded['result'] is None:
            self.send_error_msg("Missing result in solution.")
            return

        job_id = decoded['job_id']
        nonce = decoded['nonce']
        nonce = nonce.decode("hex")[::-1].encode("hex") # Reverse the order
        result = decoded['result']

        self.pool_relay_solution(job_id, nonce, result)

    def shutdown(self):
        self.send_error_msg("WebSocket bridge shutting down.")
        self.sendClose()
        self.prn("WebSocket connection closed.")

    def onMessage(self, payload, isBinary):
        if isBinary:
            self.prn("Binary message received: {0} bytes".format(len(payload)))
            self.send_error_msg("Unsupported")
            return
        else:
            self.prn("Text message received: {0}".format(
                payload.decode('utf8')))
            try:
                decoded = json.loads(payload)
            except:
                self.send_error_msg("Invalid JSON")
                return

            if 'identifier' not in decoded:
                self.send_error_msg("Invalid protocol")
                return

            identifier = decoded['identifier']
            if identifier == "handshake":
                self.handle_handshake(decoded)
                return
            elif identifier == "solved":
                self.handle_solved(decoded)
                return
            else:
                self.send_error_msg("Unknown identifier")
                return

    def onClose(self, wasClean, code, reason):
        if self.stratum is not None:
            self.stratum.terminate()
        self.prn("WebSocket connection closed: {0}".format(reason))


def main():
    log.startLogging(sys.stdout)

    # Create the websocket bridge and listen for connections from web miners.
    factory = WebSocketServerFactory(u"ws://%s:%d" % (HOSTNAME, PORT))
    factory.protocol = BridgeProtocol

    reactor.listenTCP(PORT, factory)
    reactor.run()


if __name__ == '__main__':
    main()

