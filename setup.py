from setuptools import setup
import datetime
today=datetime.date.today().strftime("%Y.%-m.%-d")
setup(
    name='musicbrainz-genre',
    version='0.1.'+today+'.dev2',
    packages=['beetsplug/musicbrainz-genre/' ],
    package_data={'beetsplug/musicbrainz-genre/': ['genres.txt']},
    include_package_data=True,
    license='MIT',
    long_description=open('README.txt').read(),
)
