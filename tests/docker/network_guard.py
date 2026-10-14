"""Deny external Python socket connections in the offline fixture processes."""

import socket


def install():
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def allowed(address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("External network prohibited by offline verification fixture")

    def guarded_connect(self, address):
        allowed(address)
        return connect(self, address)

    def guarded_connect_ex(self, address):
        allowed(address)
        return connect_ex(self, address)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
