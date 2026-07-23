import asyncio
import socket
import smtplib

import aiosmtplib


class AdapterNotFoundError(Exception):
    def __init__(self, channel: str, adapter_name: str):
        self.channel = channel
        self.adapter_name = adapter_name
        super().__init__(f"Adapter '{adapter_name}' not found for channel '{channel}'")


class AdapterConfigError(Exception):
    def __init__(self, adapter_name: str, reason: str):
        self.adapter_name = adapter_name
        self.reason = reason
        super().__init__(f"Adapter '{adapter_name}' configuration error: {reason}")


RETRYABLE_EXCEPTIONS = (
    # smtplib
    smtplib.SMTPConnectError,
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPHeloError,
    # socket
    socket.timeout,
    socket.gaierror,
    socket.herror,
    ConnectionError,
    OSError,
    # asyncio
    asyncio.TimeoutError,
    # aiosmtplib
    aiosmtplib.SMTPConnectError,
    aiosmtplib.SMTPServerDisconnected,
    aiosmtplib.SMTPConnectTimeoutError,
    aiosmtplib.SMTPTimeoutError,
    aiosmtplib.SMTPReadTimeoutError,
    aiosmtplib.SMTPHeloError,
)


NON_RETRYABLE_EXCEPTIONS = (
    # smtplib
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPDataError,
    smtplib.SMTPNotSupportedError,
    smtplib.SMTPResponseException,
    # aiosmtplib
    aiosmtplib.SMTPAuthenticationError,
    aiosmtplib.SMTPRecipientRefused,
    aiosmtplib.SMTPRecipientsRefused,
    aiosmtplib.SMTPSenderRefused,
    aiosmtplib.SMTPDataError,
    aiosmtplib.SMTPNotSupported,
    aiosmtplib.SMTPResponseException,
    # common / programming errors
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
)
