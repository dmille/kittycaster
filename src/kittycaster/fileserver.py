# fileserver.py
import os
import http.server
import socketserver
import threading
from functools import partial

from .logger import logger  # your existing logger setup


class LoggingHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    Custom request handler that logs to our KittyCaster logger
    instead of printing to stdout.
    """

    def log_message(self, format, *args):
        # Overridden to use logger instead of printing
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


# Keep global references so we can stop the server gracefully
server_instance = None
server_thread = None


def start_http_server(directory: str, port: int):
    """
    Starts a local HTTP server in a background thread, serving `directory` at `port`.
    """
    global server_instance, server_thread

    if not directory:
        logger.info("No serve_local_folder specified, skipping file server startup.")
        return

    directory = os.path.abspath(os.path.expanduser(directory))

    Handler = partial(LoggingHTTPRequestHandler, directory=directory)
    logger.info("Starting local file server in '%s' on port %d...", directory, port)

    # Use our custom LoggingTCPServer
    server_instance = LoggingTCPServer(("", port), Handler)

    def serve_forever():
        logger.info("Serving folder '%s' at http://0.0.0.0:%d/", directory, port)
        server_instance.serve_forever()

    # Start the server on a daemon thread
    server_thread = threading.Thread(target=serve_forever, daemon=True)
    server_thread.start()


def stop_http_server():
    """
    Cleanly stop the HTTP server if running.
    """
    global server_instance, server_thread
    if server_instance:
        logger.info("Shutting down local file server...")
        server_instance.shutdown()
        server_instance.server_close()
        server_instance = None
        server_thread = None
        logger.info("File server stopped.")
