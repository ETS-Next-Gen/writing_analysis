'''
Client Configuration
====================

This module creates a client-side configuration. This might include
things such as:

- Relative URL paths
- Per-server UX tweaks
- Etc.
'''

import aiohttp

import learning_observer.settings
import learning_observer.auth.http_basic

client_config = {
    # Tell the client there's a live server
    #
    # For debugging / devel, it's helpful to be able to mock the API
    # with static files. Those won't do things like web sockets.
    "mode": "server",
    "modules": {  # Per-module config
        'wobserver': {
            'hide-labels': False  # TODO: Should be loaded from config file.
        }
    },
    "google-oauth": "google-oauth" in learning_observer.settings.settings['auth'],
    "password-auth": "password-file" in learning_observer.settings.settings['auth'],
    "http-basic-auth": learning_observer.auth.http_basic.http_auth_page_enabled(),
    "theme": learning_observer.settings.settings['theme']
}


async def client_config_handler(request):
    '''
    Return a configuration JSON response to the client. This:
    - Tells the client this is running from a live server
    - Includes any system-specific configuration
    '''
    return aiohttp.web.json_response(client_config)
