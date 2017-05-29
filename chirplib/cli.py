from __future__ import print_function

import sys
import time
import logging
from os import path
from configparser import ConfigParser
from logging.handlers import RotatingFileHandler

from raven import Client

from chirplib.chirp import Chirp
from chirplib import __version__ as chirp_version

LOG_FILE = "/var/log/chirp/chirp.log"


def configure_logger():
    """
    Creates a rotating log

    :param dir_path: String, path to current directory
    """
    # Formatting
    formatter = logging.Formatter('[%(levelname)s %(asctime)s] %(message)s')

    # Set up STDOUT handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(formatter)

    # Set up file logging with rotating file handler
    rotate_fh = RotatingFileHandler(LOG_FILE, backupCount=5, maxBytes=1000000)
    rotate_fh.setLevel(logging.DEBUG)
    rotate_fh.setFormatter(formatter)

    # Create Logger object
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(stdout_handler)
    logger.addHandler(rotate_fh)

    return logger


def main():
    begin = time.time()
    # Setup the logger
    logger = configure_logger()

    logger.info("Chirp run starting")

    # Load the configuration options
    logger.info("Loading Chirp Configuration")
    config = ConfigParser()
    config_path = path.join(path.dirname(__file__), u'chirp.ini')
    config.read(config_path)

    try:
        Chirp(config, logger).find_and_post_memes()
    except Exception:  # pylint: disable=W0703
        logger.exception("Caught exception:")
        if 'sentry' in config:
            key, secret = config['sentry']['key'], config['sentry']['secret']
            url = 'https://{0}:{1}@sentry.io/173421'.format(key, secret)
            Client(url, release=chirp_version).captureException()

    logger.info("Chirp run completed in {0}".format(time.time()-begin))


if __name__ == "__main__":
    main()
