GMusicFS
========

This is a [FUSE](http://fuse.sourceforge.net/) filesystem for
[Google Music](http://music.google.com) written in Python. It utilizes the
unofficial
[gmusicapi](https://github.com/simon-weber/Unofficial-Google-Music-API)
written by Simon Weber.

### This creates a filesystem that does the following:

 * Creates a directory of ```artists/<name of artist>/<albums>/<tracks>```.
 * Access the cover image for each album as ```cover.jpg``` in the album directory.
 * Stream each track as an mp3 directly from the filesystem.
 
### What this is useful for:

 * Copying a few tracks from Google Music directly to your hard drive
   (using a file manager or ```cp``` directly.)
 * Streaming music with ```mplayer``` or another simple music player.
 
### What this is NOT useful for (yet..):

 * Importing all your music into iTunes, banshee, amarok etc. These
   big media players will attempt to read all the ID3 information from
   the files and not knowing that all the files are on a remote server. 
   It might work, but it's going to be extremely inefficient and this
   might bring down the banhammer from Google..
 * Importing new music. The filesystem is read-only (this might change 
   in a new version.)
 * Random-access within the mp3 files. You cannot seek() inside the
   mp3 files, they will only stream from the beginning of the file.

GMusicFS doesn't implement any caching. Copying a file should always work,
because latency doesn't matter, but if you're streaming the music, you 
may want to turn on your player's caching system (eg. mplayer -cache 200.)
You may notice a few blips in the sound during the first few seconds of
each song without it. If you're on a low latency connection this might not 
affect you.

Installation
------------

Installing GMusicFS requires two dependencies which currently cannot
be resolved automatically:

 * [fusepy](https://github.com/terencehonles/fusepy)
 * [gmusicapi](https://github.com/simon-weber/Unofficial-Google-Music-API)

Neither of these are able to be installed via setuptools at the
current time. fusepy due to
[this bug](https://github.com/terencehonles/fusepy/pull/9) and
we currently require the development version of gmusicapi which is not
on PyPI yet. No worries, we can install the dependencies manually:

```
pip install https://github.com/terencehonles/fusepy/tarball/master
pip install https://github.com/simon-weber/Unofficial-Google-Music-API/tarball/develop
```

Then install GMusicFS:

```
pip install https://github.com/EnigmaCurry/GMusicFS/tarball/master
```


Usage
-----

Create a config file in ```~/.gmusicfs```:

```
[credentials]
username = your_username@gmail.com
password = your_password
```

If you use 2-factor authentication, make sure you use an application
specific password.

Secure the configuration file so that no one else can read it
(GMusicFS will complain about this if you forget):
```
chmod 600 ~/.gmusicfs
```

### Command line parameters:

```
usage: gmusicfs.py [-h] [-f] [-v] [-vv] mountpoint

GMusicFS

positional arguments:
  mountpoint          The location to mount to

optional arguments:
  -h, --help          show this help message and exit
  -f, --foreground    Don't daemonize, run in the foreground.
  -v, --verbose       Be a little verbose
  -vv, --veryverbose  Be very verbose
```

Example
-------

Mount your music:

```
mkdir -p $HOME/google_music
gmusicfs $HOME/google_music
```

Unmount your music:
```
fusermount -u $HOME/google_music
```
