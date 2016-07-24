from __future__ import print_function

import random
from datetime import datetime as dt

import praw
import twitter
import MySQLdb as mdb
from retryz import retry
from twitter import TwitterError
from praw.errors import HTTPException

from chirplib.memes import ImgurMeme, DankMeme, UndigestedError

IN_DB = "In database"
POSTED = "Posted"


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
        for meme in self._meme_gen():
            try:
                ret_status = self.post_to_twitter(meme)
            except TwitterError:
                self.logger.exception("Caught TwitterError:")
                continue

            if ret_status:
                break
        else:
            log = "Couldn't find a fresh meme to post. Exiting"
            self.logger.info(log)

    def _meme_gen(self):
        """ Meme generator. Queries subreddits and tracks supplied memes
        """
        sr_memes = {sub: None for sub in self.subreddits}

        keep_generating = True
        while keep_generating:
            # Pick a random subreddit that might still have viable memes
            unchecked = [sub for sub in self.subreddits if sr_memes[sub] is None]
            incomplete = [sub for sub in self.subreddits if sub not in unchecked]
            incomplete = [sub for sub in incomplete if not all(sr_memes[sub].values())]
            sub = random.choice(unchecked + incomplete)

            # If we haven't already, get memes for that subreddit
            if sr_memes[sub] is None:
                sr_memes[sub] = dict()
                memes = self._get_subreddit_memes(sub)
                for meme in memes:
                    sr_memes[sub][meme] = IN_DB if self.in_collection(meme) else None

            # Get a meme
            memes = [m for m in sr_memes[sub] if sr_memes[sub][m] is None]
            meme = random.sample(memes, len(memes))[0]

            try:
                if isinstance(meme, ImgurMeme):
                    meme.digest()
            except Exception:  # pylint: disable=C0103, W0612, W0703
                self.logger.exception("Caught exception while digesting Imgur meme")
            else:
                yield meme
            finally:
                sr_memes[sub][meme] = POSTED

            # Check to see if we should exit
            # Are all the subreddits in the tracking dict?
            all_subs = all([sr_memes[sub] is not None for sub in self.subreddits])
            # Have we attempted to post all the memes in the tracking dict?
            all_tried = all([all(sub.values()) for sub in sr_memes.values() if sub is not None])
            keep_generating = not all_subs or not all_tried

    def _get_subreddit_memes(self, subreddit):
        '''
        Collect top memes from subreddit
        '''
        self.logger.debug("Collecting memes from subreddit: {0}".format(subreddit))

        # Build the user_agent, this is important to conform to Reddit's rules
        user_agent = 'linux:chirpscraper:0.0.1 (by /u/IHKAS1984)'
        self.logger.info("User agent: {0}".format(user_agent))

        # Create connection object
        r_client = praw.Reddit(user_agent=user_agent)

        # Get list of memes, filtering out NSFW entries
        try:
            subreddit_memes = self._get_memes_from_subreddit(r_client, subreddit)
        except HTTPException:
            log = "API failed to get memes for subreddit: {0}"
            self.logger.exception(log.format(subreddit))
            return

        memes = list()
        for meme in subreddit_memes:
            if meme.over_18 and not self.include_nsfw:
                continue

            if "imgur.com/" in meme.url:
                memes.append(ImgurMeme(meme.url, subreddit))
            else:
                memes.append(DankMeme(meme.url, subreddit))

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

    def post_to_twitter(self, meme):
        '''
        Post the memes to twitter
        '''
        log = "Posting meme to twitter:\n\t{0}"
        self.logger.info(log.format(meme))

        api = twitter.Api(consumer_key=self.twitter['consumer_key'],
                          consumer_secret=self.twitter['consumer_secret'],
                          access_token_key=self.twitter['access_token_key'],
                          access_token_secret=self.twitter['access_token_secret'])

        try:
            message, media_link = meme.format_for_twitter()
        except UndigestedError:
            log = "Caught exception while formatting Imgur meme"
            self.logger.exception(log)
            message = "#memes #dankmemes #funny #{0}".format(meme.source)
            media_link = meme.link

        try:
            api.PostUpdate(status=message, media=media_link)
        except TwitterError:
            raise
        except Exception:
            log = "Caught exception while posting to Twitter"
            self.logger.exception(log)
            ret_status = False
        else:
            self.add_to_collection(meme)
            ret_status = True

        return ret_status
