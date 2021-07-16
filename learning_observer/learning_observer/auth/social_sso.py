"""
Authentication for Google.

This was based on
[aiohttp-login](https://github.com/imbolc/aiohttp-login/), which at
the time worked with outdated Google APIs and require Jinja2. Oren
modernized this. Piotr integrated this into the system.

Portions of this file, from aiohttp-login, are licensed as:

Copyright (c) 2011 Imbolc.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

Eventually, this should be broken out into its own module.
"""

import yarl

import aiohttp
import aiohttp.web
import aiohttp_session

# TODO: We might want to not import this, but pass this info, to make
# this file generic, and not specific to learning_observer.
import learning_observer.settings as settings
import learning_observer.auth.handlers as handlers
import learning_observer.auth.utils

import learning_observer.exceptions


async def social_handler(request):
    """Handles Google sign in.

    Provider is in `request.match_info['provider']` (currently, only Google)
    """
    if request.match_info['provider'] != 'google':
        raise learning_observer.exceptions.SuspiciousOperation(
            "We only handle Google logins. Non-google Provider"
        )

    user = await _google(request)

    if 'user_id' in user:
        await learning_observer.auth.utils.update_session_user_info(request, user)

    if user['authorized']:
        url = user['back_to'] or "/"
    else:
        url = "/"

    return aiohttp.web.HTTPFound(url)


async def _google(request):
    '''
    Handle Google login
    '''
    if 'error' in request.query:
        return {}

    common_params = {
        'client_id': settings.settings['auth']['google-oauth']['web']['client_id'],
        'redirect_uri': "https://pddeane.com/auth/login/google",
    }

    # Step 1: redirect to get code
    if 'code' not in request.query:
        url = 'https://accounts.google.com/o/oauth2/auth'
        params = common_params.copy()
        params.update({
            'response_type': 'code',
            'scope': (
                'https://www.googleapis.com/auth/userinfo.profile'
                ' https://www.googleapis.com/auth/userinfo.email'
                ' https://www.googleapis.com/auth/classroom.courses.readonly'
                ' https://www.googleapis.com/auth/classroom.rosters.readonly'
                ' https://www.googleapis.com/auth/classroom.profile.emails'
                ' https://www.googleapis.com/auth/classroom.profile.photos'
            ),
        })
        if 'back_to' in request.query:
            params['state'] = request.query['back_to']
        url = yarl.URL(url).with_query(params)
        raise aiohttp.web.HTTPFound(url)

    # Step 2: get access token
    url = 'https://accounts.google.com/o/oauth2/token'
    params = common_params.copy()
    params.update({
        'client_secret': settings.settings['auth']['google-oauth']['web']['client_secret'],
        'code': request.query['code'],
        'grant_type': 'authorization_code',
    })
    async with aiohttp.ClientSession(loop=request.app.loop) as client:
        async with client.post(url, data=params) as resp:
            data = await resp.json()
        assert 'access_token' in data, data

        # get user profile
        headers = {'Authorization': 'Bearer ' + data['access_token']}
        session = await aiohttp_session.get_session(request)
        session["auth_headers"] = headers
        request["auth_headers"] = headers

        # Old G+ URL that's no longer supported.
        url = 'https://www.googleapis.com/oauth2/v1/userinfo'
        async with client.get(url, headers=headers) as resp:
            profile = await resp.json()

    return {
        'user_id': profile['id'],
        'email': profile['email'],
        'name': profile['given_name'],
        'family_name': profile['family_name'],
        'back_to': request.query.get('state'),
        'picture': profile['picture'],
        # TODO: Should this be immediate?
        'authorized': await learning_observer.auth.utils.verify_teacher_account(profile['id'], profile['email'])
    }
