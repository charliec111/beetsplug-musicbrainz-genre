Import genre tags from musicbrainz.
If there is a musicbrainz login, it will be used for user tags (tags you've 
upvoted). This can be disabled with user_genres: False in the config.
Tags will be user tags first, then most votes to least votes (but >= min votes) in each of track, then album, then artist.

Install with:
pip install git+https://github.com/charliec111/beetsplug-musicbrainz-genre.git

Or, if you use pipx for a venv called beets:
pipx runpip beets install git+https://github.com/charliec111/beetsplug-musicbrainz-genre.git

Features:
Run 'beet musicbrainz-genre {query}' to add genres to a subset. Set auto in the config to run on import.

The minimum votes for track, album and artist can be set in the config.
Track, album, and artist searching can be enabled/disabled in the config with search_track etc.
'auto: True' (default) will add genres on import, 'auto: False' will not.
ask_to_confirm: True will ask before setting each genre on import
ask_to_confirm_command: True will ask before setting each genre when using 'beet musicbrainz-genre [query]'

This may take a bit of time for a large query to respect musicbrainz documentation requesting no more than
one request per second (it's set to pause until 1.1 seconds have elapsed since the last request). Each tag is cached
in a dict for each run so if you disable searching by track by setting 'search_track: False' in the config it will run
faster at the expense of per track genres (which MB doesn't have a ton of anyway), since it would only have to
request once per album and once per artist.

config example:

musicbrainz:
  genres: no
  user: User
  pass: 'hunter2'
musicbrainz-genre:
  auto: True
  search_track: True
  search_album: True
  search_artist: True
  separator: ", "
  track_min_genre_votes: 1
  album_min_genre_votes: 2
  artist_min_genre_votes: 5
  max_genres: 3
  ask_to_confirm_command: False
  ask_to_confirm: False
