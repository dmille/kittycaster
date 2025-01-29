import os
import http.server
import socketserver
import threading
from functools import partial

from .logger import logger


class LoggingHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    Custom request handler that logs to our KittyCaster logger
    instead of printing to stdout, and registers/unregisters
    client connections with the server so we can forcibly close them.
    """

    def setup(self):
        """
        Called before 'handle()'. We'll register this socket with 'open_connections'.
        """
        super().setup()
        # self.server is our ThreadedLoggingTCPServer instance
        # self.connection is the actual socket for this request
        if hasattr(self.server, "open_connections"):
            self.server.open_connections.add(self.connection)

    def finish(self):
        """
        Called after 'handle()' completes. We'll unregister this socket.
        """
        if hasattr(self.server, "open_connections"):
            self.server.open_connections.discard(self.connection)
        super().finish()

    def log_message(self, format, *args):
        logger.info(
            "%s - - [%s] %s",
            self.address_string(),
            self.log_date_time_string(),
            format % args,
        )


class LoggingTCPServer(socketserver.TCPServer):
    """
    A TCPServer that overrides handle_error so we can handle
    exceptions (like ConnectionResetError) via our logger
    rather than printing a traceback.
    """

    def handle_error(self, request, client_address):
        import sys

        ex_type, ex_value, tb = sys.exc_info()
        if isinstance(ex_value, ConnectionResetError):
            logger.info("Client at %s reset the connection.", client_address)
        else:
            logger.exception("Error processing request from %s", client_address)


class ThreadedLoggingTCPServer(socketserver.ThreadingMixIn, LoggingTCPServer):
    """
    A ThreadingMixIn + our custom LoggingTCPServer.
    Each request runs in its own thread, allowing server.shutdown()
    to succeed quickly even if a client is mid-download.
    """

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        # We'll track all active client sockets in a set:
        self.open_connections = set()


# Keep global references so we can stop the server gracefully
server_instance = None
server_thread = None


def start_http_server(directory: str, port: int):
    """
    Starts a local HTTP server in a background thread, serving `directory` at `port`.
    Uses a threaded server so shutdown won't block on active requests.
    """
    global server_instance, server_thread

    if not directory:
        logger.info("No serve_local_folder specified, skipping file server startup.")
        return

    directory = os.path.abspath(os.path.expanduser(directory))

    Handler = partial(LoggingHTTPRequestHandler, directory=directory)
    logger.info("Starting local file server in '%s' on port %d...", directory, port)

    server_instance = ThreadedLoggingTCPServer(("", port), Handler)

    def serve_forever():
        logger.info("Serving folder '%s' at http://0.0.0.0:%d/", directory, port)
        server_instance.serve_forever()

    server_thread = threading.Thread(target=serve_forever, daemon=True)
    server_thread.start()


def stop_http_server(force_close=False):
    """
    Cleanly stop the HTTP server if running.
    If `force_close` is True, we forcibly close all active client sockets
    before shutting down (e.g. to kill any ongoing downloads immediately).
    """
    global server_instance, server_thread
    if server_instance:
        logger.info("Shutting down local file server...")

        # Optionally, kill all in-progress connections:
        if force_close:
            logger.info("Forcibly closing all active client connections...")
            for conn in list(server_instance.open_connections):
                try:
                    conn.close()
                except Exception as e:
                    logger.warning("Error closing socket forcibly: %s", e)
            # The threads handling these sockets will error out soon.

        # Now do a normal server shutdown
        server_instance.shutdown()
        server_instance.server_close()
        server_instance = None
        server_thread = None
        logger.info("File server stopped.")
