import sys
from setuptools import setup

install_requires = [
    'fusepy',
    'gmusicapi'
]

# pip install https://github.com/terencehonles/fusepy/tarball/master
# pip install https://github.com/simon-weber/Unofficial-Google-Music-API/tarball/master

setup(
    name = 'GMusicFS',
    version = '0.1',
    description = 'A FUSE filesystem for Google Music',
    author = 'Ryan McGuire',
    author_email = 'ryan@enigmacurry.com',
    url = 'http://github.com/EnigmaCurry/GMusicFS',
    license = 'MIT',
    install_requires = install_requires,
    zip_safe=False,
    packages = ['gmusicfs'],
    entry_points = {
        'console_scripts': ['gmusicfs = gmusicfs.gmusicfs:main']},
)
