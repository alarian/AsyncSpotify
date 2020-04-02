"""
The main api class which will be used to authenticate and connect to the spotify api
"""

import base64
import json
import time
import webbrowser
from urllib import parse
from urllib.parse import urlencode

from aiohttp import ClientSession

from .api_request_maker import ApiRequestHandler
from .endpoints.albums import Albums
from .endpoints.artists import Artists
from .endpoints.urls import URLS
from .response_status import ResponseStatus
from ..authentification.spotify_authorization_token import SpotifyAuthorisationToken
from ..authentification.spotify_cookies import SpotifyCookies
from ..preferences import Preferences
from ..spotify_errors import SpotifyError


class API:
    """
    The main api class which will be used to authenticate and connect to the spotify api.
    Use this class to authenticate and connect to the spotify api.
    """

    # noinspection PyTypeChecker
    def __init__(self, preferences: Preferences, hold_authentication=False):
        """
        Create a new api class
        Args:
            preferences: The preferences object fully filled with information
            hold_authentication: Should the api keep the authentication im memory and refresh it automatically
        """

        # Check if the preferences are valid
        if not preferences.validate():
            raise SpotifyError("The preferences of your app are not correct")

        # Set the preferences
        self.preferences: Preferences = preferences

        self.hold_authentication: bool = hold_authentication
        self.spotify_authorisation_token: SpotifyAuthorisationToken = None

        self.api_request_handler: ApiRequestHandler = ApiRequestHandler(self)

        self.albums = Albums(self)
        self.artist = Artists(self)

    async def create_new_client(self, request_timeout: int = 30, request_limit: int = 500) -> None:
        """
        Create a new session which will be used to connect to the spotify api.
        In general this only has to be called once after you create a new API object.
        You can however call this method if you want ot update the client settings (more requests, ...)
        This will however close all ongoing requests.

        Args:
            request_timeout: How long should be waited for a request (default 30s) (None for no limit)
            request_limit: How many requests should be allowed (default 500)

        Returns:
            None
        """

        await self.api_request_handler.create_new_client(request_timeout, request_limit)

    async def close_client(self) -> None:
        """
        Close the current client session. You have to create a new one to connect again to spotify.
        This method should always be called before you end your program

        Returns:
            None
        """

        if self.api_request_handler:
            await self.api_request_handler.close_client()
            self.api_request_handler = None

    def build_authorization_url(self, show_dialog=True, state: str = None) -> str:
        """
        Builds the URL for the authorisation

        Args:
            state: State of the authorization
            show_dialog: Should the spotify auth dialog be shown

        Returns:
            The encoded url which can be used to authorize a new or existing user
        """

        params = {
            "client_id": self.preferences.application_id,
            "response_type": "code",
            "scope": ' '.join(self.preferences.scopes),
            "show_dialog": f"{show_dialog}",
            "redirect_uri": f"{self.preferences.redirect_url}"
        }

        # Check if a state is required
        if state:
            params["state"] = f"{state}"

        return f"{URLS.AUTHORIZE}?{urlencode(params)}"

    def open_oauth_dialog_in_browser(self, show_dialogue: bool = True) -> None:
        """
        Open the url in browser
        Only for testing purposes or the usage of this library in a desktop app

        Args:
            show_dialogue: Should the spotify auth dialog be shown

        Returns:
            None
        """

        # Open url in a new window of the default browser, if possible
        webbrowser.open_new(self.build_authorization_url(show_dialogue))

    async def get_code_with_cookie(self, cookies: SpotifyCookies) -> str:
        """
        This function takes care of the user interaction that is normally necessary to get the first code from spotify
        which is necessary to request the refresh_token and the oauth_token.
        The token that is returned by this function has to be passed to API.refresh_token(code, reauthorize=False)
        to get the refresh_token and the oauth_token.

        Note:
            This will only work if the user has at least once accepted the scopes your app is requesting.
            I would recommend that you take a look at the source code of this function before you use it and that you
            are familiar with the authorization mechanism of spotify.

        Important:
            This method is intended for automated testing. You have to decide if you want to use it in you production
            environment.

        Args:
            cookies: The cookies of the spotify account. Every property of the class has to be filled in.

        Raises:
            SpotifyError: An error occurred during the code retrieval

        Returns:
            The spotify code which can be used to get a refresh_token and a oauth_token
        """

        # Build the auth url
        url = self.build_authorization_url(show_dialog=False)

        # Check if the cookie file is valid
        if not cookies.validate():
            raise SpotifyError('The cookies are not complete')

        # Convert the class to a dict
        cookie_dict: dict = cookies.__dict__

        # Make an api request to spotify
        async with ClientSession(cookies=cookie_dict, requote_redirect_url=False) as session:
            async with session.get(url, allow_redirects=False) as resp:
                # Get the headers
                headers = resp.headers
            await session.close()

        print(resp.headers)
        print(resp.url)

        # Check if the request should have been redirected
        if 'location' not in headers:
            raise SpotifyError('There was no redirect in in the spotify response. Has the user accepted the '
                               'scopes once before or has the cookie not the right values?')

        # Get the redirect url
        location: str = headers['location']

        # Parse the url
        local_url = parse.urlparse(location)
        query = parse.parse_qs(local_url.query)

        # Check if code is the redirect url
        if 'code' not in query:
            raise SpotifyError('There was no code parameter in the redirect url')

        return query['code'][0]

    async def get_auth_token_with_code(self, code: str) -> SpotifyAuthorisationToken:
        """
        Get the auth token with the code returned by the oauth process.

        Args:
            code: The code returned by spotify in the oauth process

        Note:
            https://developer.spotify.com/documentation/general/guides/authorization-guide/#authorization-code-flow

        Raises:
            SpotifyError: If the request to the refresh api point was not successful

        Returns:
            A valid SpotifyAuthorisationToken

        """

        body: dict = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.preferences.redirect_url
        }

        response_json: dict = await self._make_auth_api_request(body)

        refresh_token: str = response_json['refresh_token']
        access_token: str = response_json['access_token']

        spotify_authorisation_token = SpotifyAuthorisationToken(refresh_token=refresh_token,
                                                                activation_time=int(time.time()),
                                                                access_token=access_token)
        # Keep the auth token in memory
        if self.hold_authentication:
            self.spotify_authorisation_token = spotify_authorisation_token

        return spotify_authorisation_token

    async def refresh_token(self, auth_token: SpotifyAuthorisationToken = None) -> SpotifyAuthorisationToken:
        """
        Refresh the auth token with the refresh token or get a new auth token and refresh token with the code returned
        by the spotify auth flow.

        Args:
            auth_token: The refresh token or the code returned by the spotify auth flow. Leave empty if you enabled
                hold_authentication. Then the internal token will be used.

        Note:
            https://developer.spotify.com/documentation/general/guides/authorization-guide/#authorization-code-flow

        Returns:
            The SpotifyAuthorisationToken
        """

        # Check if the internal auth token should be used
        if not auth_token and self.hold_authentication:
            auth_token = self.spotify_authorisation_token

        body: dict = {
            'grant_type': 'refresh_token',
            'refresh_token': auth_token.refresh_token
        }

        response_json: dict = await self._make_auth_api_request(body)

        refresh_token = auth_token.refresh_token
        access_token = response_json['access_token']
        spotify_authorisation_token = SpotifyAuthorisationToken(refresh_token=refresh_token,
                                                                activation_time=int(time.time()),
                                                                access_token=access_token)
        # Keep the auth token in memory
        if self.hold_authentication:
            self.spotify_authorisation_token = spotify_authorisation_token

        return spotify_authorisation_token

    async def _make_auth_api_request(self, body: dict) -> dict:
        """
        Make an api request to the refresh endpoint

        Args:
            body: The body of the request

        Returns:
            The access token and the refresh token if the grant_type was code
        """

        # Build the header of the request
        base_64: base64 = base64.b64encode(
            f'{self.preferences.application_id}:{self.preferences.application_secret}'.encode('ascii'))
        header: dict = {'Authorization': f'Basic {base_64.decode("ascii")}'}

        # Make the request to the api
        async with ClientSession() as session:
            async with session.post(url=URLS.REFRESH, data=body, headers=header) as response:
                response_status = ResponseStatus(response.status)
                response_text: str = await response.text()
            await session.close()

        # The response was not ok
        if not response_status.success:
            raise SpotifyError(response_status.message + '\n' + str(response_text))

        return json.loads(response_text)