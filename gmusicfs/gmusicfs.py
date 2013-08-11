#!/usr/bin/env python2

import os
import re
import sys
import urllib2
import ConfigParser
from errno import ENOENT
from stat import S_IFDIR, S_IFREG
import time
import argparse
import operator
import shutil
import tempfile
import threading
import logging

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
from gmusicapi import Mobileclient as GoogleMusicAPI
from gmusicapi import Webclient as GoogleMusicWebAPI

import fifo

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
deviceId=None

def formatNames(string_from):
    return re.sub('/', '-', string_from)


class NoCredentialException(Exception):
    pass

class Album(object):
    'Keep record of Album information'
    def __init__(self, library, normtitle):
        self.library = library
        self.normtitle = formatNames(normtitle)
        self.__tracks = []
        self.__sorted = True
        self.__filename_re = re.compile("^[0-9]{3} - (.*)\.mp3$")

    def add_track(self, track):
        'Add a track to the Album'
        self.__tracks.append(track)
        self.__sorted = False

    def get_tracks(self, get_size=False):
        # Re-sort by track number:
        if not self.__sorted:
            self.__tracks.sort(key=lambda t: t.get('track'))
        # Retrieve and remember the filesize of each track:
        if get_size and self.library.true_file_size:
            for t in self.__tracks:
                if not t.has_key('bytes'):
                    r = urllib2.Request(self.get_track_stream(t))
                    r.get_method = lambda: 'HEAD'
                    u = urllib2.urlopen(r)
                    t['bytes'] = int(u.headers['Content-Length'])
        return self.__tracks

    def get_track(self, filename):
        """Get the track name corresponding to a filename
        (eg. '001 - brilliant track name.mp3')"""
        m = self.__filename_re.match(filename)
        if m:
            title = m.groups()[0]
            for track in self.get_tracks():
                if formatNames(track['title'].lower()) == title:
                    return track
        return None

    def get_track_stream(self, track):
        "Get the track stream URL"
        print deviceId
        print deviceId
        print deviceId
        return self.library.api.get_stream_url(track['id'], deviceId)

    def get_cover_url(self):
        'Get the album cover image URL'
        try:
            #Assume the first track has the right cover URL:
            url = "%s" % self.__tracks[0]['albumArtRef'][0]['url']
        except:
            url = None
        return url

    def get_year(self):
        """Get the year of the album.
        Aggregate all the track years and pick the most popular year
        among them"""
        years = {} # year -> count
        for track in self.get_tracks():
            y = track.get('year', None)
            if y:
                count = years.get(y, 0)
                years[y] = count + 1
        top_years = sorted(years.items(),
                           key=operator.itemgetter(1), reverse=True)
        try:
            top_year = top_years[0][0]
        except IndexError:
            top_year = 0
        return top_year

    def __repr__(self):
        return u'<Album \'{title}\'>'.format(title=self.normtitle)

class MusicLibrary(object):
    'Read information about your Google Music library'

    def __init__(self, username=None, password=None,
                 true_file_size=False, scan=True, verbose=0):
        self.verbose = False
        if verbose > 1:
            self.verbose = True

        self.__login_and_setup(username, password)

        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__albums = [] # [Album(), ...]
        if scan:
            self.rescan()
        self.true_file_size = true_file_size

    def rescan(self):
        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__albums = [] # [Album(), ...]
        self.__aggregate_albums()

    def __login_and_setup(self, username=None, password=None):
        # If credentials are not specified, get them from $HOME/.gmusicfs
        if not username or not password:
            cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs')
            if not os.path.isfile(cred_path):
                raise NoCredentialException(
                    'No username/password was specified. No config file could '
                    'be found either. Try creating %s and specifying your '
                    'username/password there. Make sure to chmod 600.'
                    % cred_path)
            if not oct(os.stat(cred_path)[os.path.stat.ST_MODE]).endswith('00'):
                raise NoCredentialException(
                    'Config file is not protected. Please run: '
                    'chmod 600 %s' % cred_path)
            self.config = ConfigParser.ConfigParser()
            self.config.read(cred_path)
            username = self.config.get('credentials','username')
            password = self.config.get('credentials','password')
            global deviceId
            deviceId = self.config.get('credentials','deviceId')
            if not username or not password:
                raise NoCredentialException(
                    'No username/password could be read from config file'
                    ': %s' % cred_path)
            if not deviceId:
                raise NoCredentialException(
                    'No deviceId could be read from config file'
                    ': %s' % cred_path)

        self.api = GoogleMusicAPI(debug_logging=self.verbose)
        log.info('Logging in...')
        self.api.login(username, password)
        log.info('Login successful.')

    def __aggregate_albums(self):
        'Get all the tracks in the library, parse into artist and album dicts'
        all_artist_albums = {} # 'Artist|||Album' -> Album()
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        for track in tracks:
            # Prefer the album artist over the track artist if there is one:
            artist = formatNames(track['albumArtist'].lower())
            if artist.strip() == '':
                artist = formatNames(track['artist'].lower())
            # Get the Album object if it already exists:
            key = '%s|||%s' % (formatNames(artist), formatNames(track['album'].lower()))
            album = all_artist_albums.get(key, None)
            if not album:
                # New Album
                if artist == '':
                    artist = 'unknown'
                album = all_artist_albums[key] = Album(
                    self, formatNames(track['album'].lower()))
                self.__albums.append(album)
                artist_albums = self.__artists.get(artist, None)
                if artist_albums:
                    artist_albums[formatNames(album.normtitle)] = album
                else:
                    self.__artists[artist] = {album.normtitle: album}
                    artist_albums = self.__artists[artist]
            album.add_track(track)
        log.debug('%d tracks loaded.' % len(tracks))
        log.debug('%d artists loaded.' % len(self.__artists))
        log.debug('%d albums loaded.' % len(self.__albums))

    def get_artists(self):
        return self.__artists

    def get_albums(self):
        return self.__albums

    def get_artist_albums(self, artist):
        log.debug(artist)
        return self.__artists[artist]

    def cleanup(self):
        pass

class GMusicFS(LoggingMixIn, Operations):
    'Google Music Filesystem'
    def __init__(self, path, username=None, password=None,
                 true_file_size=False, verbose=0, scan_library=True):
        Operations.__init__(self)
        self.artist_dir = re.compile('^/artists/(?P<artist>[^/]+)$')
        self.artist_album_dir = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4}) - (?P<album>[^/]+)$')
        self.artist_album_track = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4}) - (?P<album>[^/]+)/(?P<track>[^/]+\.mp3)$')
        self.artist_album_image = re.compile(
            '^/artists/(?P<artist>[^/]+)/(?P<year>[0-9]{4}) - (?P<album>[^/]+)/(?P<image>[^/]+\.jpg)$')

        self.__open_files = {} # path -> urllib2_obj

        # login to google music and parse the tracks:
        self.library = MusicLibrary(username, password,
                                    true_file_size=true_file_size, verbose=verbose, scan=scan_library)
        log.info("Filesystem ready : %s" % path)

    def cleanup(self):
        self.library.cleanup()

    def getattr(self, path, fh=None):
        'Get info about a file/dir'
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)
        artist_album_image_m = self.artist_album_image.match(path)

        # Default to a directory
        st = {
            'st_mode' : (S_IFDIR | 0755),
            'st_nlink' : 2 }
        date = time.time()
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date

        if path == '/':
            pass
        elif path == '/artists':
            pass
        elif artist_dir_m:
            pass
        elif artist_album_dir_m:
            pass
        elif artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            track = album.get_track(parts['track'])
            st = {
                'st_mode' : (S_IFREG | 0444),
                'st_size' : int(track['estimatedSize']),
                'st_ctime' : int(track['creationTimestamp']) / 1000000,
                'st_mtime' : int(track['creationTimestamp']) / 1000000,
                'st_atime' : int(track['recentTimestamp']) / 1000000}
        elif artist_album_image_m:
            st = {
                'st_mode' : (S_IFREG | 0444),
                'st_size' : 10000000 }
        else:
            raise FuseOSError(ENOENT)

        return st

    def open(self, path, fh):
        artist_album_track_m = self.artist_album_track.match(path)
        artist_album_image_m = self.artist_album_image.match(path)

        if artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            track = album.get_track(parts['track'])
            url = album.get_track_stream(track)
        elif artist_album_image_m:
            parts = artist_album_image_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            url = album.get_cover_url()
            print url
            print url
            print url
            print url
            print url
        else:
            RuntimeError('unexpected opening of path: %r' % path)

        u = self.__open_files[fh] = urllib2.urlopen(url)
        u.bytes_read = 0

        return fh

    def __open_multi_part(self, urls, path):
        """Starts a thread to download a multi-part track (Google Play All
        Access) into a single file in the cache directory and return
        an open file handle for it while it downloads.
        """
        buf = fifo.Buffer()
        # Start downloading the multi part track in another thread:
        downloader = AllAccessTrackDownloader(urls, buf, path)
        downloader.start()
        # Return the buffer, while the download is still happening:
        return buf

    def release(self, path, fh):
        u = self.__open_files.get(fh, None)
        if u:
            u.close()
            del self.__open_files[fh]

    def read(self, path, size, offset, fh):
        u = self.__open_files.get(fh, None)
        if u is None:
            raise RuntimeError('unexpected path: %r' % path)
        else:
            buf = u.read(size)
            try:
                u.bytes_read += size
            except AttributeError:
                # Only urllib2 files need this attribute, harmless to
                # ignore it.
                pass
            return buf

    def readdir(self, path, fh):
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)
        artist_album_image_m = self.artist_album_image.match(path)

        if path == '/':
            return ['.', '..', 'artists']
        elif path == '/artists':
            return  ['.','..'] + self.library.get_artists().keys()
        elif artist_dir_m:
            # Artist directory, lists albums.
            albums = self.library.get_artist_albums(
                artist_dir_m.groupdict()['artist'])
            # Sort albums by year:
            album_dirs = [u'{year:04d} - {name}'.format(
                year=a.get_year(), name=formatNames(a.normtitle)) for a in albums.values()]
            return ['.','..'] + album_dirs
        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            files = ['.','..']
            for track in album.get_tracks(get_size=True):
                files.append('%03d - %s.mp3' % (track['trackNumber'], formatNames(track['title'].lower())))
            # Include cover image:
            cover = album.get_cover_url()
            if cover:
                files.append('cover.jpg')
            return files

class AllAccessTrackDownloader(threading.Thread):
    """Multi-part track downloader"""
    def __init__(self, urls, writer, path, buffer_bytes=32000):
        self.urls = urls
        self.writer = writer
        self.path = path
        threading.Thread.__init__(self)
        self.buffer_bytes = buffer_bytes

    def run(self):
        byte_num = 0
        for url in self.urls:
            range_start, range_end = re.search(r'range=([0-9]*)-([0-9]*)', url).groups()
            range_start, range_end = (int(range_start), int(range_end))
            log.info("Downloading multi-part track: %s" % url)
            u = urllib2.urlopen(url)
            # There is overlap between parts, so skip the part that we already have:
            u.read(byte_num - range_start)
            # Buffer the rest of the file and write it as it comes:
            while True:
                data = u.read(self.buffer_bytes)
                if data == '':
                    break
                byte_num += len(data)
                self.writer.write(data)
        log.info("Done downloading multi-part track: %s" % self.path)
        self.writer.close()


def getDeviceId(verbose=False):
    cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs')
    if not os.path.isfile(cred_path):
        raise NoCredentialException(
            'No username/password was specified. No config file could '
            'be found either. Try creating %s and specifying your '
            'username/password there. Make sure to chmod 600.'
            % cred_path)
    if not oct(os.stat(cred_path)[os.path.stat.ST_MODE]).endswith('00'):
        raise NoCredentialException(
            'Config file is not protected. Please run: '
            'chmod 600 %s' % cred_path)
    config = ConfigParser.ConfigParser()
    config.read(cred_path)
    username = config.get('credentials','username')
    password = config.get('credentials','password')
    if not username or not password:
        raise NoCredentialException(
            'No username/password could be read from config file'
            ': %s' % cred_path)

    api = GoogleMusicWebAPI(debug_logging=verbose)
    log.info('Logging in...')
    api.login(username, password)
    log.info('Login successful.')

    for device in api.get_registered_devices():
        if not device['name']:
            device['name']='NoName'
        if device['id'][1]=='x':
            print '%s : %s' % (device['name'], device['id'])

def main():
    log.setLevel(logging.WARNING)
    logging.getLogger('gmusicapi').setLevel(logging.WARNING)
    logging.getLogger('fuse').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description='GMusicFS', add_help=False)
    parser.add_argument('--deviceid', action='store_true', dest='deviceId')
    parser.add_argument('-h', action="store_true", dest='h')

    args = parser.parse_args()
    if args.deviceId:
        getDeviceId()
        return

    parser = argparse.ArgumentParser(description='GMusicFS')
    parser.add_argument('mountpoint', help='The location to mount to')
    parser.add_argument('-f', '--foreground', dest='foreground',
                        action="store_true",
                        help='Don\'t daemonize, run in the foreground.')
    parser.add_argument('-v', '--verbose', help='Be a little verbose',
                        action='store_true', dest='verbose')
    parser.add_argument('-vv', '--veryverbose', help='Be very verbose',
                        action='store_true', dest='veryverbose')
    parser.add_argument('-t', '--truefilesize', help='Report true filesizes'
                        ' (slower directory reads)',
                        action='store_true', dest='true_file_size')
    parser.add_argument('--allusers', help='Allow all system users access to files'
                        ' (Requires user_allow_other set in /etc/fuse.conf)',
                        action='store_true', dest='allusers')
    parser.add_argument('--nolibrary', help='Don\'t scan the library at launch',
                        action='store_true', dest='nolibrary')
    parser.add_argument('--deviceid', help='Get the device ids bounded to your account',
                        action='store_true', dest='deviceId')

    args = parser.parse_args()

    mountpoint = os.path.abspath(args.mountpoint)

    # Set verbosity:
    if args.veryverbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('gmusicapi').setLevel(logging.DEBUG)
        logging.getLogger('fuse').setLevel(logging.DEBUG)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 10
    elif args.verbose:
        log.setLevel(logging.INFO)
        logging.getLogger('gmusicapi').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.INFO)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 1
    else:
        log.setLevel(logging.WARNING)
        logging.getLogger('gmusicapi').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.WARNING)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 0




    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, scan_library= not args.nolibrary)
    try:
        fuse = FUSE(fs, mountpoint, foreground=args.foreground,
                    ro=True, nothreads=True, allow_other=args.allusers)
    finally:
        fs.cleanup()

if __name__ == '__main__':
    main()
