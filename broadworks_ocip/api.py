"""
Broadworks OCI-P Interface API Class and code

Main API interface - this is basically the only consumer visible part
"""
import hashlib
import inspect
import logging
import select
import socket
import sys
import uuid

from classforge import Class
from classforge import Field
from lxml import etree

import broadworks_ocip.base
import broadworks_ocip.requests
import broadworks_ocip.responses
import broadworks_ocip.types
from broadworks_ocip.exceptions import OCIErrorTimeOut


FORMATTER = logging.Formatter(
    "%(asctime)s — %(name)s — %(levelname)s — %(funcName)s:%(lineno)d — %(message)s",
)


class BroadworksAPI(Class):
    """ """

    session = Field(type=str)
    host = Field(type=str, required=True)
    port = Field(type=int, default=2208)
    username = Field(type=str, required=True)
    password = Field(type=str, required=True)
    logger = Field(type=object)
    despatch_table = Field(type=dict)
    authenticated = Field(type=bool, default=False)
    connect_timeout = Field(type=int, default=8)
    command_timeout = Field(type=int, default=30)
    socket = Field(type=object, default=None)

    def on_init(self):
        """ """
        if self.session is None:
            self.session = str(uuid.uuid4())
        if self.logger is None:
            self.configure_logger()
        self.build_despatch_table()
        self.authenticated = False

    def build_despatch_table(self):
        """ """
        self.logger.debug("Building Broadworks despatch table")
        despatch_table = {}
        # deal with all the main request/responses
        for module in (broadworks_ocip.responses, broadworks_ocip.requests):
            for name, data in inspect.getmembers(module, inspect.isclass):
                if name.startswith("__"):
                    continue
                try:
                    if data.__module__ in (
                        "broadworks_ocip.types",
                        "broadworks_ocip.requests",
                        "broadworks_ocip.responses",
                    ):
                        despatch_table[name] = data
                except AttributeError:
                    continue
        # deal with special cases in base
        for name, data in inspect.getmembers(broadworks_ocip.base, inspect.isclass):
            if name in ("SuccessResponse", "ErrorResponse"):
                despatch_table[name] = data
                despatch_table["c:" + name] = data  # namespace issues
        # we now have a despatch table...
        self.despatch_table = despatch_table
        self.logger.debug("Built Broadworks despatch table")

    def configure_logger(self):
        """ """
        logger = logging.getLogger("broadworks_api")
        logger.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(FORMATTER)
        logger.addHandler(console_handler)
        self.logger = logger

    def get_command_class(self, command):
        try:
            cls = self.despatch_table[command]
        except KeyError as e:
            self.logger.error(f"Unknown command requested - {command}")
            raise e
        return cls

    def get_command_xml(self, command, **kwargs):
        """

        :param command:
        :param **kwargs:

        """
        cls = self.get_command_class(command)
        cmd = cls(_session=self.session, **kwargs)
        return cmd._build_xml()

    def send_command(self, command, **kwargs):
        """

        :param command:
        :param **kwargs:

        """
        self.logger.info(f">>> {command}")
        xml = self.get_command_xml(command, **kwargs)
        self.logger.debug(f"SEND: {str(xml)}")
        self.socket.sendall(xml + b"\n")

    def receive_response(self):
        """ """
        content = b""
        while True:
            readable, writable, exceptional = select.select(
                [self.socket],
                [],
                [],
                self.command_timeout,
            )
            if readable:  # there is only one thing in the set...
                content += self.socket.recv(4096)
                # look for the end of document marker (we ignore line ends)
                splits = content.partition(b"</BroadsoftDocument>")
                if len(splits[1]) > 0:
                    break
            elif not readable and not writable and not exceptional:
                raise OCIErrorTimeOut(object=self, message="Read timeout")
        self.logger.debug(f"RECV: {str(content)}")
        return self.decode_xml(content)

    def decode_xml(self, xml):
        """

        :param xml:

        """
        root = etree.fromstring(xml)
        if root.tag != "{C}BroadsoftDocument":
            raise ValueError
        self.logger.debug("Decoding BroadsoftDocument")
        for element in root:
            if element.tag == "command":
                command = element.get("{http://www.w3.org/2001/XMLSchema-instance}type")
                self.logger.debug(f"Decoding command {command}")
                cls = self.despatch_table[command]
                result = cls._build_from_etree(element)
                self.logger.info(f"<<< {result._type}")
                result._post_xml_decode()
                return result

    def connect(self):
        """ """
        self.logger.debug(f"Attempting connection host={self.host} port={self.port}")
        try:
            address = (self.host, self.port)
            conn = socket.create_connection(
                address=address,
                timeout=self.connect_timeout,
            )
            self.socket = conn
            self.logger.info(f"Connected to host={self.host} port={self.port}")
        except OSError as e:
            self.logger.error("Connection failed")
            raise e
        except socket.timeout as e:
            self.logger.error("Connection timed out")
            raise e

    def authenticate(self):
        """ """
        self.send_command("AuthenticationRequest", user_id=self.username)
        resp = self.receive_response()
        authhash = hashlib.sha1(self.password.encode()).hexdigest().lower()
        signed_password = (
            hashlib.md5(":".join([resp.nonce, authhash]).encode()).hexdigest().lower()
        )
        self.send_command(
            "LoginRequest14sp4",
            user_id=self.username,
            signed_password=signed_password,
        )
        # if this fails to authenticate an ErrorResponse will be returned which forces
        # an exception to be raised
        resp = self.receive_response()
        # if authentication failed this line will never be executed
        self.authenticated = True

    def command(self, command, **kwargs):
        """

        :param command:
        :param **kwargs:

        """
        if not self.authenticated:
            self.connect()
            self.authenticate()
        self.send_command(command, **kwargs)
        return self.receive_response()

    def close(self):
        """ """
        if self.authenticated:
            self.logger.debug("Disconnect by logging out")
            self.send_command(
                "LogoutRequest",
                user_id=self.username,
                reason="Connection close",
            )
            self.authenticated = False
        if self.socket:
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            self.logger.info(f"Disconnected from host={self.host} port={self.port}")
            self.socket = None

    def __del__(self):
        self.close()


# end
