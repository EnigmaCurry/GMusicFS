#!/usr/bin/env python2

import os
import re
import sys
import urllib2
import ConfigParser
from errno import ENOENT
from stat import S_IFDIR, S_IFREG
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
import time
from gmusicapi.api import Api as GoogleMusicAPI
import argparse
import operator

import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')

class NoCredentialException(Exception):
    pass

class Album(object):
    'Keep record of Album information'
    def __init__(self, api, normtitle):
        self.api = api
        self.normtitle = normtitle
        self.__tracks = []
        self.__sorted = True
        self.__filename_re = re.compile("^[0-9]{3} - (.*)\.mp3$")

    def add_track(self, track):
        'Add a track to the Album'
        self.__tracks.append(track)
        self.__sorted = False

    def get_tracks(self):
        # Re-sort by track number:
        if not self.__sorted:
            self.__tracks.sort(key=lambda t: t.get('track'))
        return self.__tracks

    def get_track(self, filename):
        """Get the track name corresponding to a filename 
        (eg. '001 - brilliant track name.mp3')"""
        m = self.__filename_re.match(filename)
        if m:
            title = m.groups()[0]
            for track in self.get_tracks():
                if track['titleNorm'] == title:
                    return track
        return None

    def get_track_stream(self, track):
        "Get the track stream URL"
        return self.api.get_stream_url(track['id'])

    def get_cover_url(self):
        'Get the album cover image URL'
        try:
            #Assume the first track has the right cover URL:
            url = "http:%s" % self.__tracks[0]['albumArtUrl']
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
    
    def __init__(self, username=None, password=None):
        self.__artists = {} # 'artist name' -> {'album name' : Album(), ...}
        self.__albums = [] # [Album(), ...]
        self.__login(username, password)
        self.__aggregate_albums()

    def __login(self, username=None, password=None):
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
            config = ConfigParser.ConfigParser()
            config.read(cred_path)
            username = config.get('credentials','username')
            password = config.get('credentials','password')
            if not username or not password:
                raise NoCredentialException(
                    'No username/password could be read from config file'
                    ': %s' % cred_path)
            
        self.api = GoogleMusicAPI()
        log.info('Logging in...')
        self.api.login(username, password)
        log.info('Login successful.')
        
    def __aggregate_albums(self):
        'Get all the tracks in the library, parse into artist and album dicts'
        all_artist_albums = {} # 'Artist|||Album' -> Album()
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        for track in tracks:
            # Get the Album object if it already exists:
            key = '%s|||%s' % (track['artistNorm'], track['albumNorm'])
            album = all_artist_albums.get(key, None)
            if not album:
                # New Album
                artist = track['artistNorm']
                if artist == '':
                    artist = 'unknown'
                album = all_artist_albums[key] = Album(
                    self.api, track['albumNorm'])
                self.__albums.append(album)
                artist_albums = self.__artists.get(artist, None)
                if artist_albums:
                    artist_albums[album.normtitle] = album
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

class GMusicFS(LoggingMixIn, Operations):
    'Google Music Filesystem'
    def __init__(self, path, username=None, password=None):
        Operations.__init__(self)
        self.artist_dir = re.compile('^/artists/(?P<artist>[^/]+)$')
        self.artist_album_dir = re.compile(
            '^/artists/(?P<artist>[^/]+)/[0-9]{4} - (?P<album>[^/]+)$')
        self.artist_album_track = re.compile(
            '^/artists/(?P<artist>[^/]+)/[0-9]{4} - (?P<album>[^/]+)/(?P<track>[^/]+\.mp3)$')
        self.artist_album_image = re.compile(
            '^/artists/(?P<artist>[^/]+)/[0-9]{4} - (?P<album>[^/]+)/(?P<image>[^/]+\.jpg)$')

        self.__open_files = {} # path -> urllib2_obj

        # login to google music and parse the tracks:
        self.library = MusicLibrary(username, password)
        log.info("Filesystem ready : %s" % path)

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

        if path == '/':
            pass
        if path == '/artists':
            pass
        elif artist_dir_m:
            pass
        elif artist_album_dir_m:
            pass
        elif artist_album_track_m:
            st = {
                'st_mode' : (S_IFREG | 0444),
                'st_size' : 200000000 }
        elif artist_album_image_m:
            st = {
                'st_mode' : (S_IFREG | 0444),
                'st_size' : 10000000 }
        else:
            raise FuseOSError(ENOENT)

        # Set some create, modify, and access times
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date
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
        else:
            RuntimeError('unexpected opening of path: %r' % path)
        u = self.__open_files[fh] = urllib2.urlopen(url)
        u.bytes_read = 0
        return fh

    def release(self, path, fh):
        u = self.__open_files.get(fh, None)
        if u:
            u.close()
            del self.__open_files[fh]
    
    def read(self, path, size, offset, fh):
        u = self.__open_files.get(fh, None)
        if u:
            buf = u.read(size)
            u.bytes_read += size
            return buf
        else:
            raise RuntimeError('unexpected path: %r' % path)

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
            album_dirs = ['{year:04d} - {name}'.format(
                year=a.get_year(), name=a.normtitle) for a in albums.values()]
            return ['.','..'] + album_dirs
        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            album = self.library.get_artists()[
                parts['artist']][parts['album']]
            files = ['.','..']
            for track in album.get_tracks():
                files.append('%03d - %s.mp3' % (track['track'], 
                                                track['titleNorm']))
            # Include cover image:
            cover = album.get_cover_url()
            if cover:
                files.append('cover.jpg')
            return files
    
def main():
    parser = argparse.ArgumentParser(description='GMusicFS')
    parser.add_argument('mountpoint', help='The location to mount to')
    parser.add_argument('-f', '--foreground', dest='foreground', 
                        action="store_true",
                        help='Don\'t daemonize, run in the foreground.')
    parser.add_argument('-v', '--verbose', help='Be a little verbose',
                        action='store_true', dest='verbose')
    parser.add_argument('-vv', '--veryverbose', help='Be very verbose',
                        action='store_true', dest='veryverbose')
    args = parser.parse_args()

    mountpoint = os.path.abspath(args.mountpoint)
    
    # Set verbosity:
    if args.veryverbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('gmusicapi.Api').setLevel(logging.DEBUG)
        logging.getLogger('fuse').setLevel(logging.DEBUG)
    elif args.verbose:
        log.setLevel(logging.INFO)
        logging.getLogger('gmusicapi.Api').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARNING)
        logging.getLogger('gmusicapi.Api').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.WARNING)
        
    fuse = FUSE(GMusicFS(mountpoint), mountpoint, foreground=args.foreground, 
                ro=True, nothreads=True)

if __name__ == '__main__':
    main()
