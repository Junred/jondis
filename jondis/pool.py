from Queue import Queue
from itertools import chain
import os
from redis import ConnectionError
from redis.connection import Connection
from redis.client import parse_info
from collections import namedtuple

Server = namedtuple('Server', ['host', 'port'])


class Pool(object):

    def __init__(self, connection_class=Connection,
                 max_connections=None, hosts=[],
                 **connection_kwargs):

        self.pid = os.getpid()
        self.connection_class = connection_class
        self.connection_kwargs = connection_kwargs
        self.max_connections = max_connections or 2 ** 31
        self._in_use_connections = set()

        self._hosts = set() # current active known hosts
        self._current_master = None # (host,port)

        self._master_pool = set()
        self._slave_pool = set()

        for x in hosts:
            if ":" in x:
                (host, port) = x.split(":")

            else:
                host = x
                port = 6379

            self._hosts.add(Server(host, int(port)))

        self._configure()

    def _configure(self):
        """
        given the servers we know about, find the current master
        once we have the master, find all the slaves
        """
        to_check = Queue()
        for x in self._hosts:
            to_check.put(x)

        while not to_check.empty():
            x = to_check.get()

            try:
                conn = self.connection_class(host=x.host, port=x.port, **self.connection_kwargs)
                conn.send_command("INFO")
                info = parse_info(conn.read_response())

                if info['role'] == 'slave':
                    self._slave_pool.add(conn)
                elif info['role'] == 'master':
                    self._master_pool.add(conn)
                    slaves = filter(lambda x: x[0:5] == 'slave', info.keys())
                    slaves = [info[y] for y in slaves]
                    slaves = [y.split(',') for y in slaves]
                    slaves = filter(lambda x: x[2] == 'online', slaves)
                    slaves = [Server(x[0], int(x[1])) for x in slaves]

                    for y in slaves:
                        if y not in self._hosts:
                            self._hosts.add(y)
                            to_check.put(y)

                    # add the slaves

            except:
                # remove from list
                to_remove = []


    def _checkpid(self):
        if self.pid != os.getpid():
            self.disconnect()
            self.__init__(self.connection_class, self.max_connections,
                          **self.connection_kwargs)

    def get_connection(self, command_name, *keys, **options):
        "Get a connection from the pool"
        self._checkpid()
        try:
            connection = self._master_pool.pop()
        except IndexError:
            connection = self.make_connection()

        self._in_use_connections.add(connection)
        return connection

    def make_connection(self):
        "Create a new connection"
        if self._created_connections >= self.max_connections:
            raise ConnectionError("Too many connections")
        self._created_connections += 1
        return self.connection_class(**self.connection_kwargs)

    def release(self, connection):
        "Releases the connection back to the pool"
        self._checkpid()
        if connection.pid == self.pid:
            self._in_use_connections.remove(connection)
            self._master_pool.add(connection)

    def disconnect(self):
        "Disconnects all connections in the pool"
        all_conns = chain(self._master_pool,
                          self._in_use_connections)
        for connection in all_conns:
            connection.disconnect()

