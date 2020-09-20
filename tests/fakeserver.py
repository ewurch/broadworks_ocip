# This code is based on https://medium.com/@hmajid2301/pytest-with-background-thread-fixtures-f0dc34ee3c46
import logging
import socket
import sys

from broadworks_ocip import BroadworksAPI

FORMATTER = logging.Formatter(
    "%(asctime)s — %(name)s — %(levelname)s — %(funcName)s:%(lineno)d — %(message)s",
)

BASIC_API_PARAMS = {
    "host": "localhost",
    "username": "username@example.com",
    "password": "password",
    "session": "00000000-1111-2222-3333-444444444444",
}


class FakeServer:
    def __init__(self, port=0):
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.stream = None
        self.configure_logger()
        self.logger.debug("Instantiated FakeServer")

    def __enter__(self):
        self.socket.bind(("127.0.0.1", self.port))
        host, port = self.socket.getsockname()
        self.logger.debug(f"Listening on tcp://{host}:{port}")
        self.port = port
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if self.stream is not None:
            self.stream.close()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            # this seems to happen...
            pass
        self.socket.close()
        self.logger.info(f"Disconnected socket port={self.port}")

    def listen_for_traffic(self):
        while True:
            self.socket.listen(5)
            connection, address = self.socket.accept()
            (host, port) = address
            self.logger.info(f"Connection from host={host} port={port}")
            stream = connection.makefile(mode="rb")
            self.stream = stream
            api = BroadworksAPI(**BASIC_API_PARAMS)
            while True:
                try:
                    content = b""
                    while True:
                        line = self.stream.readline()
                        content += line
                        if line.endswith(b"</BroadsoftDocument>\n"):
                            break
                    self.logger.debug(f"RECV: {str(content)}")
                    self.process_command(connection, content, api)
                except ValueError:
                    self.logger.debug("Connection had been closed on me")
                    return

    def configure_logger(self):
        """ """
        logger = logging.getLogger("fake_server")
        logger.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(FORMATTER)
        logger.addHandler(console_handler)
        self.logger = logger

    def process_command(self, connection, content, api):
        cmd = api.decode_xml(content)
        self.logger.debug(f"F<<<: {cmd._type}")
        response = None
        if cmd._type == "AuthenticationRequest":
            cls = api.get_command_class("AuthenticationResponse")
            response = cls(
                user_id=cmd.user_id,
                nonce="1234567890123",
                password_algorithm="MD5",
            )
        elif cmd._type == "LoginRequest14sp4":
            domain = cmd.user_id.partition("@")[2]
            if domain == "":
                domain = "example.org"
            cls = api.get_command_class("LoginResponse14sp4")
            response = cls(
                login_type="System",
                locale="en_GB",
                encoding="ISO-8859",
                is_enterprise=False,
                user_domain=domain,
            )
        elif cmd._type == "SystemSoftwareVersionGetRequest":
            cls = api.get_command_class("SystemSoftwareVersionGetResponse")
            response = cls(version="21sp1")
        else:
            cls = api.get_command_class("ErrorResponse")
            response = cls(
                error_code="0001",
                summary="Server is a fake and a fraud",
                summary_english="This is not a real server and doesn't implement many things",
                detail="There might be more detail if this was a real server",
                type="abject_panic",
            )
        response._session = cmd._session
        self.logger.debug(f"Built response {cmd._type}")
        xml = response._build_xml()
        self.logger.debug(f"F>>>: {response._type}")
        connection.sendall(xml + b"\n")
        self.logger.debug(f"SEND: {str(xml)}")
