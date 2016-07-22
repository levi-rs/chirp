from __future__ import print_function

import random
from datetime import datetime as dt

import praw
import twitter
import MySQLdb as mdb
from retryz import retry
from praw.errors import HTTPException

from chirplib.memes import ImgurMeme, DankMeme, UndigestedError


class Chirp(object):  # pylint: disable=R0902, R0903
    '''
    Bot for posting dank memes from Reddit to Twitter
    '''
    def __init__(self, config, logger):
        # pylint: disable=too-many-instance-attributes

        self.twitter = config['twitter']

        self.database = config['mysql']['database']
        self.username = config['mysql']['username']
        self.password = config['mysql']['password']

        self.include_nsfw = config.getboolean('misc', 'include_nsfw')
        self.max_memes = config.getint('misc', 'max_memes')

        self.subreddits = [s.strip(',') for s in config['reddit']['subreddits'].split()]

        # Get and set Imgur API credentials
        client_id = config['imgur']['client_id']
        client_secret = config['imgur']['client_secret']

        ImgurMeme.set_credentials(client_id=client_id, client_secret=client_secret)

        # Get logger
        self.logger = logger

    def find_and_post_memes(self):
        """ Find memes from subreddits and post them to Twitter
        """
        # Check for most recent dank memes
        memes = self.get_memes()
        self.logger.info("Found {0} memes".format(len(memes)))

        # Filter out any known dank memes
        filtered_memes = [m for m in memes if not self.in_collection(m)]
        self.logger.info(
            "Removed {0} known memes".format(len(memes) - len(filtered_memes)))

        # Shuffle memes
        random.shuffle(filtered_memes)

        # Cut down to the max memes
        pared_memes = filtered_memes[:self.max_memes]
        self.logger.info("Truncated to {0} memes".format(len(pared_memes)))

        # Bale here if nothing is left
        if not pared_memes:
            self.logger.info("No fresh memes to post, exiting")
            return False

        # If any memes are Imgur memes, get more information
        for meme in [meme for meme in pared_memes if isinstance(meme, ImgurMeme)]:
            log = "Attempting to get more info on Imgur meme: {0}"
            self.logger.info(log.format(meme))
            try:
                meme.digest()
            except Exception:  # pylint: disable=C0103, W0612, W0703
                self.logger.exception("Caught exception while digesting Imgur meme")

        # Post to twitter
        return self.post_to_twitter(pared_memes)

    def get_memes(self):
        '''
        Collect top memes from subreddits specified in chirp.ini
        '''

        # Build the user_agent, this is important to conform to Reddit's rules
        user_agent = 'linux:chirpscraper:0.0.1 (by /u/IHKAS1984)'
        self.logger.info("User agent: {0}".format(user_agent))

        # Create connection object
        r_client = praw.Reddit(user_agent=user_agent)

        memes = list()

        # Get list of memes, filtering out NSFW entries
        for sub in self.subreddits:
            self.logger.debug("Collecting memes from subreddit: {0}".format(sub))
            try:
                subreddit_memes = self._get_memes_from_subreddit(r_client, sub)
            except HTTPException:
                log = "API failed to get memes for subreddit: {0}"
                self.logger.exception(log.format(sub))
                continue

            for meme in subreddit_memes:
                if meme.over_18 and not self.include_nsfw:
                    continue

                if "imgur.com/" in meme.url:
                    memes.append(ImgurMeme(meme.url, sub))
                else:
                    memes.append(DankMeme(meme.url, sub))

        return memes

    @staticmethod
    @retry(on_error=HTTPException, limit=3, wait=2)
    def _get_memes_from_subreddit(client, subreddit):
        return client.get_subreddit(subreddit).get_hot()

    def in_collection(self, meme):
        '''
        Checks to see if the supplied meme is already in the collection of known
        memes
        '''
        query = "SELECT * FROM memes WHERE links = '%s'" % meme.link

        con = mdb.connect(
            'localhost',
            self.username,
            self.password,
            self.database,
            charset='utf8'
        )

        with con, con.cursor() as cur:
            try:
                resp = cur.execute(query)
            except UnicodeEncodeError:
                # Indicates a link with oddball characters, just ignore it
                resp = True

                log = "Bad character in meme: {0}"
                self.logger.exception(log.format(meme))

        return True if resp else False

    def add_to_collection(self, meme):
        '''
        Adds a meme to the collection
        '''
        query = """INSERT INTO memes
                   (links, sources, datecreated)
                   VALUES
                   ('%s', '%s', '%s')
                """ % (meme.link, meme.source, str(dt.now()))

        con = mdb.connect(
            'localhost',
            self.username,
            self.password,
            self.database,
            charset='utf8'
        )

        with con, con.cursor() as cur:
            cur.execute(query)

        return

    def post_to_twitter(self, memes):
        '''
        Post the memes to twitter
        '''
        # TODO: replace slack stuff with twitter stuff
        log = "Posting {0} memes to twitter:\n\t{1}"
        self.logger.info(log.format(len(memes), "\n\t".join([str(m) for m in memes])))
        ret_status = False

        api = twitter.Api(consumer_key=self.twitter['consumer_key'],
                          consumer_secret=self.twitter['consumer_secret'],
                          access_token_key=self.twitter['access_token_key'],
                          access_token_secret=self.twitter['access_token_secret'])

        for meme in memes:
            try:
                message, media_link = meme.format_for_twitter()
            except UndigestedError:
                log = "Caught exception while formatting Imgur meme"
                self.logger.exception(log)

                message, media_link = "#memes #dankmemes #funny #{0}".format(meme.source), meme.link

            try:
                api.PostUpdate(status=message, media=media_link)
            except:
                log = "Caught exception while posting to Twitter"
                self.logger.exception(log)
                ret_status = False
            else:
                self.add_to_collection(meme)
                ret_status = True

        return ret_status
