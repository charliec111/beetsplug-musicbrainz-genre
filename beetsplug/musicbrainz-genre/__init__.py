# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.


import re
import os
from beets import config, dbcore, ui
from beets.dbcore import types
from beets.ui import decargs, print_
from beets.util import normpath
from beets.plugins import BeetsPlugin
from time import sleep

import musicbrainzngs as mb
import requests
import datetime
from string import capwords

# These files were copied from beetbox beets's lastgenre plugin under MIT license
WHITELIST = os.path.join(os.path.dirname(__file__), "genres.txt")
C14N_TREE = os.path.join(os.path.dirname(__file__), "genres-tree.yaml")

VERSION = "0.3a"
mb.set_useragent("beetsplug-musicbrainz-genre", f"{VERSION}", "(https://github.com/charliec111/beetsplug-musicbrainz-genre)")
requests_headers = {
    "User-Agent": f"beetsplug-musicbrainz-genre {VERSION} (https://github.com/charliec111/beetsplug-musicbrainz-genre)",
}
# To reduce number of queries to listenbrainz, album and artist are only queried once
responses = {}


class MusicBrainzGenrePlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.overwrite = True
        self.log = self._log
        self.whitelist = None
        self.item_types = {}
        self.write_to_file = True
        config["musicbrainz"].add(
            {
                "user": None,
                "pass": None,
            }
        )
        self.config.add(
            {
                "ask_to_confirm_command": True,
                "ask_to_confirm": False,
                "auto": True,
                "whitelist": True,
                "separator": ", ",
                "title_case": True,
                "search_track": True,
                "search_album": True,
                "search_artist": True,
                "track_min_genre_votes": 1,
                "album_min_genre_votes": 2,
                "artist_min_genre_votes": 5,
                "max_genres": 5,
                "url": "https://musicbrainz.org/ws/2/",
                "user-genres": True,
            }
        )
        self.track_min_genre_votes = self.config["track_min_genre_votes"].as_number()
        self.album_min_genre_votes = self.config["album_min_genre_votes"].as_number()
        self.artist_min_genre_votes = self.config["artist_min_genre_votes"].as_number()
        self.max_genres = self.config["max_genres"].as_number()
        self.ask_to_confirm = bool(self.config["ask_to_confirm"])
        self.ask_to_confirm_command = bool(self.config["ask_to_confirm_command"])
        self.title_case = bool(self.config["title_case"])
        self.search_track = bool(self.config["search_track"])
        self.search_album = bool(self.config["search_album"])
        self.search_artist = bool(self.config["search_artist"])
        self.separator = self.config["separator"].as_str()
        self.musicbrainz_base_url = self.config["url"].as_str()
        self.user_genres = bool(self.config["user_genres"]) if "user_genres" in self.config else True
        self.no_mb_queries_until = datetime.datetime.now()
        self.pretend = False
        if not self.whitelist:
            self.whitelist = set()
            wl_filename = WHITELIST
            # These lines copied from lastgenre plugin in beetbox beets
            if wl_filename:
                wl_filename = normpath(wl_filename)
                with open(wl_filename, "rb") as f:
                    for line in f:
                        line = line.decode("utf-8").strip().lower()
                        if line and not line.startswith("#"):
                            self.whitelist.add(line)
        try:
            if config["musicbrainz"]["user"] and config["musicbrainz"]["pass"]:
                mb_user=config["musicbrainz"]["user"].as_str()
                mb_password=config["musicbrainz"]["pass"].as_str()
                mb.auth(mb_user, mb_password)
        except Exception as e:
            self.user_genres = False
            self._log.warning("MusicBrainz user and pass not set correctly in config.yaml")
            mb_user=None
            mb_password=None
        if self.config["auto"]:
            self.import_stages = [self.imported]

    def commands(self):
        autoartists = ui.Subcommand("musicbrainz-genre", help="musicbrainz-genre")
        autoartists.parser.add_option(
            "-p",
            "--pretend",
            dest="pretend",
            action="store_true",
            default=False,
            help="Don't write genre tags, only search and output the result",
        )
        autoartists.parser.add_option(
            "-W",
            "--nowrite",
            dest="nowrite",
            action="store_true",
            default=False,
            help="Don't write genre tags to file",
        )
        autoartists.parser.add_option(
            "--ask",
            dest="ask",
            action="store_true",
            default=False,
            help="Ask before writing each tag",
        )
        autoartists.parser.add_option(
            "--no-overwrite",
            dest="dontoverwrite",
            action="store_true",
            default=False,
            help="Don't overwrite if genres are already present",
        )
        autoartists.func = self.func
        return [autoartists]

    def func(self, lib, opts, args):
        self.pretend = opts.pretend
        query_result_songs = lib.items(decargs(args))
        self.ask_to_confirm = self.ask_to_confirm_command
        if opts.ask:
            self.ask_to_confirm = opts.ask
        self.overwrite = not opts.dontoverwrite
        self.write_to_file = not opts.nowrite
        if self.pretend:
            print_(f"Pretending to set genre for {len(query_result_songs)} songs")
        else:
            print_(f"Setting genre for {len(query_result_songs)} songs")
        for song in query_result_songs:
            self.set_genre(song)
            print_(str(song) + ": " + song["genre"])

    def imported(self, session, task):
        for item in task.imported_items():
            self.set_genre(item)

    def set_genre(self, song):
        genres = []
        # Moving whitelist to init, may be slower since it's loading it every beet (incl when not needed)
        #if not self.whitelist:
        #    self.whitelist = set()
        #    wl_filename = WHITELIST
        #    # These lines copied from lastgenre plugin in beetbox beets
        #    if wl_filename:
        #        wl_filename = normpath(wl_filename)
        #        with open(wl_filename, "rb") as f:
        #            for line in f:
        #                line = line.decode("utf-8").strip().lower()
        #                if line and not line.startswith("#"):
        #                    self.whitelist.add(line)
        if self.ask_to_confirm or self.pretend:
            logger = print_
        else:
            logger = self.log.debug
        if not self.overwrite and "genre" in song and len(song["genre"]) > 0:
            logger(f"{song} already has genres {song.genre}, not overwriting")
            return
        if (
            self.search_track
            and len(genres) < self.max_genres
            and "mb_trackid" in song
            and is_valid_mbid(song["mb_trackid"])
        ):
            song_recording_mbid = song["mb_trackid"]
            response = self.get_mb_request("recording/", song_recording_mbid)
            logger("---")
            if response:
                if self.user_genres and "user-tag-list" in response:
                    for i in [
                            i
                            for i in response["user-tag-list"]
                            if i["name"] in self.whitelist
                        ]:
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding user track genre {genre}")
                            genres.append(genre)
                if "tag-list" in response:
                    for i in sorted(
                        [
                            i
                            for i in response["tag-list"]
                            if int(i["count"]) >= self.track_min_genre_votes
                        ],
                        reverse=True,
                        key=lambda x: x["count"],
                    ):
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding track genre {genre}")
                            genres.append(genre)
        if (
            self.search_album
            and len(genres) < self.max_genres
            and "mb_releasegroupid" in song
            and is_valid_mbid(song["mb_releasegroupid"])
        ):
            song_album_mbid = song["mb_releasegroupid"]
            response = self.get_mb_request("release-group/", song_album_mbid)
            if response:
                if self.user_genres and "user-tag-list" in response:
                    for i in [
                            i
                            for i in response["user-tag-list"]
                            if i["name"] in self.whitelist
                        ]:
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding user track genre {genre}")
                            genres.append(genre)
                if "tag-list" in response:
                    for i in sorted(
                        [
                            i
                            for i in response["tag-list"]
                            if int(i["count"]) >= self.album_min_genre_votes
                        ],
                        reverse=True,
                        key=lambda x: x["count"],
                    ):
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding album genre {genre}")
                            genres.append(genre)
        # check mb_albumid only when mb_releasegroupid is not available
        elif (
            self.search_album
            and len(genres) < self.max_genres
            and "mb_albumid" in song
            and is_valid_mbid(song["mb_albumid"])
        ):
            song_album_mbid = song["mb_albumid"]
            response = self.get_mb_request("release/", song_album_mbid)
            if response:
                if self.user_genres and "user-tag-list" in response:
                    for i in [
                            i
                            for i in response["user-tag-list"]
                            if i["name"] in self.whitelist
                        ]:
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding user album genre {genre}")
                            genres.append(genre)
                if "tag-list" in response:
                    for i in sorted(
                        [
                            i
                            for i in response["tag-list"]
                            if int(i["count"]) >= self.album_min_genre_votes
                        ],
                        reverse=True,
                        key=lambda x: x["count"],
                    ):
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding album genre {genre}")
                            genres.append(genre)
        if (
            self.search_artist
            and len(genres) < self.max_genres
            and "mb_artistid" in song
            and is_valid_mbid(song["mb_artistid"])
        ):
            song_artist_mbid = song["mb_artistid"]
            response = self.get_mb_request("artist/", song_artist_mbid)
            if response:
                if self.user_genres and "user-tag-list" in response:
                    for i in [
                            i
                            for i in response["user-tag-list"]
                            if i["name"] in self.whitelist
                        ]:
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding user artist genre {genre}")
                            genres.append(genre)
                if "tag-list" in response:
                    for i in sorted(
                        [
                            i
                            for i in response["tag-list"]
                            if int(i["count"]) >= self.artist_min_genre_votes
                        ],
                        reverse=True,
                        key=lambda x: x["count"],
                    ):
                        if self.title_case:
                            genre = capwords(i["name"])
                        else:
                            genre = i["name"]
                        if genre not in genres and (
                            self.whitelist is None or genre.lower() in self.whitelist
                        ):
                            self.log.debug(f"Adding artist genre {genre}")
                            genres.append(genre)
        if len(genres) == 0:
            self.log.debug(f"{song}: No genres found")
            return
        genres = genres[0 : self.max_genres]
        confirm = "n"
        if self.ask_to_confirm or self.pretend:
            logger(str((song)))
            if "genre" in song:
                logger(f"Current genres: {song.genre}")
            logger("New genres: " + self.separator.join(genres))
        # for i in [ x for x in genres if x.lower() not in self.whitelist ]:
        #    logger(f"Not whitelisted: {i}")
        if self.ask_to_confirm:
            confirm = input(f"Save new genres (yes/no): ").lower()
        if not self.pretend and (not self.ask_to_confirm or confirm in ["y", "yes"]):
            song["genre"] = self.separator.join(genres)
            song.store()
            if self.write_to_file:
                song.try_write()

    # Input:
    # type_url is the string like "release-group/" for the applicable musicbrainz group of the mbid
    # mbid is the mbid for the type specified
    # Output:
    # Returns the response if status code is 200, otherwise returns None

    # the type_url arg is a bit wonky. there may be a way of inferring it from mbid,
    # It's here because I was using requests.get before, which needed the full url.
    # Now it's using musicbrainzngs, so it's using it to know which function to call.
    def get_mb_request(self, type_url, mbid):
        if mbid in responses:
            return responses[mbid]
        if not is_valid_mbid(mbid):
            return None
        
        wait_until(self.no_mb_queries_until)
        mb_func = None
        try:
            match type_url:
                case "recording/":
                    mb_func = mb.get_recording_by_id
                    response = mb_func(mbid, includes=["user-tags","tags"])['recording']
                case "release-group/":
                    mb_func = mb.get_release_group_by_id
                    response = mb_func(mbid, includes=["user-tags","tags"])['release-group']
                case "release/":
                    mb_func = mb.get_release_by_id
                    response = mb_func(mbid, includes=["user-tags","tags"])['release']
                case "artist/":
                    mb_func = mb.get_artist_by_id
                    response = mb_func(mbid, includes=["user-tags","tags"])['artist']
        except mb.ResponseError as e:
            self.log.error(f"MusicBrainz response error when searching for genres for {mbid}")
            responses[mbid] = None
            return None
        except KeyError: 
            responses[mbid] = None
            return None
        if "user-tag-list" in response:
            response["user-tag-list"] = [ i for i in response["user-tag-list"] if i["name"] in self.whitelist ]
        if "tag-list" in response:
            response["tag-list"] = [ i for i in response["tag-list"] if i["name"] in self.whitelist ]
        #print(response)
        if ( "user-tag-list" not in response or len(response["user-tag-list"]) == 0 ) and ( "tag-list" not in response or len(response["tag-list"]) == 0 ):
            responses[mbid] = None
        responses[mbid] = response
        # MusicBrainz api documentation asks for no more than 1 query per second, this will set
        # a datetime object 1100 ms in the future for the wait_until function to wait for.
        # 1100 milliseconds to be safe
        self.no_mb_queries_until = datetime.datetime.now() + datetime.timedelta(
            milliseconds=1250
        )
        return response
        # Old method:
        # Not using this anymore because I kept getting errors trying to auth with musicbrainz
        # Using requests instead of musicbrainzngs or similar because I
        # couldn't find genres, only tags from musicbrainzngs
        #parameters = {"inc": "genres", "fmt": "json"}
        #try:
        #    wait_until(self.no_mb_queries_until)
        #    # print(datetime.datetime.now())
        #    try:
        #        response = requests.get(
        #            self.musicbrainz_base_url + type_url + mbid,
        #            timeout=5,
        #            params=parameters,
        #            headers=requests_headers,
        #        )
        #    except:
        #        return None
        #    # MusicBrainz api documentation asks for no more than 1 query per second, this will set
        #    # a datetime object 1100 ms in the future for the wait_until function to wait for.
        #    # 1100 milliseconds to be safe
        #    self.no_mb_queries_until = datetime.datetime.now() + datetime.timedelta(
        #        milliseconds=1250
        #    )
        #except requests.exceptions.MissingSchema:
        #    self.log.error(
        #        f"When searching musicbrainz for genres, invalid url missing schema (possibly missing http:// or https://): {self.musicbrainz_base_url}"
        #    )
        #    #return None
        #    exit(1)
        #except requests.exceptions.ConnectionError:
        #    self.log.error(f"Connection error when searching musicbrainz for genres: {self.musicbrainz_base_url}")
        #    #exit(1)
        #    return None
        #if response.status_code == 200:
        #    responses[mbid] = response
        #    return response
        #else:
        #    responses[mbid] = None
        #    return None


mbid_regex = r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$"
mbid_regex_compiled = re.compile(mbid_regex)
def is_valid_mbid(mbid):
    return mbid_regex_compiled.match(mbid.lower())


# mostly copied from https://stackoverflow.com/a/54774814
def wait_until(end_datetime):
    while True:
        diff = (end_datetime - datetime.datetime.now()).total_seconds()
        if diff < 0:
            return  # In case end_datetime was in past to begin with
        sleep(diff / 2)
        if diff <= 0.1:
            sleep(diff)
            return
