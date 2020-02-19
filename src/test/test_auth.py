import time

import pytest

from async_spotify import SpotifyAuthorisationToken, API
from async_spotify.preferences import Preferences


class TestAuth():

    def test_load_secret_preferences(self):
        preferences = Preferences()
        preferences.load_from_docker_secret()

        assert False is preferences.validate()

    def test_load_os_preferences(self):
        preferences = Preferences()
        preferences.load_from_env()

        assert preferences.validate()

    def test_save_preferences_to_env(self):
        original_data = Preferences()
        original_data.load_from_env()

        preferences = Preferences("test", "test", ["test", "test"], "test")
        preferences.save_preferences_to_evn()

        loaded_preferences = Preferences()
        loaded_preferences.load_from_env()

        original_data.save_preferences_to_evn()

        assert preferences == loaded_preferences

    def test_auth_url(self, preferences: Preferences):
        api = API(preferences)
        url = api.build_authorization_url(show_dialog=False, state="TestState")
        assert ("show_dialog=False" in url and "state=TestState" in url)

    def test_not_expired_token(self):
        token = SpotifyAuthorisationToken("some random string", int(time.time()), "Another random string")
        assert False is token.is_expired()

    def test_expired_token(self):
        token = SpotifyAuthorisationToken("some random string", int(time.time()) - 3401, "Another random string")
        assert token.is_expired()

    @pytest.mark.asyncio
    async def test_code_retrieval(self, api: API):
        spotify_code = await api.get_code_with_cookie("/home/runner/work/AsyncSpotify/AsyncSpotify/cookies.txt")
        assert spotify_code["code"] != ""
