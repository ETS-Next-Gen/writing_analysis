'''
Common utility functions for working with analytics modules.

The goal is to have the modules be pluggable and independent of the
system. For now, our overall system diagram is:

+---------------+
|               |                                   +-------------+
| Event Source  ---|                                | Key-Value   |
|               |  |                                | Store       |
+---------------+  |                                |             |
+---------------+  |          +-----------+  <------|-- Internal  |
|               |  |          |           |  -------|-> State     |       +------------+      +------------+
| Event Source  --------|---->| Reducer   |         |             |       |            |      |            |
|               |   |   |     |           | --------|-> External -------->| Aggregator |----> | Dashboard  |
+---------------+   |   |     +-----------+         |   State     |       |            |      |            |
+---------------+   |   |                           |             |       +------------+      +------------+
|               |   |   |                           +-------------+
| Event Source  ----|   |
|               |       |
+---------------+       v
                  +------------+
                  |            |
                  |  Archival  |
                  | Repository |
                  |            |
                  +------------+

We create reducers with the `kvs_pipeline` decorator. In the longer
term, we'll want to be able to plug together different aggregators,
state types, etc. We'll also want different keys for reducers
(per-student, per-resource, etc.). For now, though, this works.
'''
import enum
import functools

import learning_observer.kvs


KeyStateType = enum.Enum("KeyStateType", "INTERNAL EXTERNAL")


def fully_qualified_function_name(func):
    '''
    Takes a function. Return a fully-qualified string with a name for
    that function. E.g.:

    >>> from math import sin
    >>> fully_qualified_function_name(math.sin)
    'math.sin'

    This is helpful for then giving unique names to analytics modules. Each module can
    be uniquely referenced based on its reduce function.
    '''
    return "{module}.{function}".format(
        module=func.__module__,
        function=func.__qualname__
    )


def make_key(func, safe_user_id, state_type):
    '''
    Create a KVS key

    This joins a stream module ID, a sanitized user ID, and
    whether this is the internal state of the module or the
    external state.
    '''
    # pylint: disable=isinstance-second-argument-not-valid-type
    assert isinstance(state_type, KeyStateType)
    assert callable(func)

    streammodule = fully_qualified_function_name(func)

    return "{state_type}:{streammodule}:{user}".format(
        state_type=state_type.name.capitalize(),
        streammodule=streammodule,
        user=safe_user_id
    )


def kvs_pipeline(
        null_state=None
):
    '''
    Closures, anyone?

    There's a bit to unpack here.

    Top-level function. This allows us to configure the decorator (and
    returns the decorator).

    * `null_state` tells us the empty state, before any reduce operations have
      happened. This can be important for the aggregator. We're documenting the
      code before we've written it, so please make sure this works before using.
    '''
    def decorator(func):
        '''
        The decorator itself
        '''
        @functools.wraps(func)
        def wrapper_closure(metadata):
            '''
            The decorator itself. We create a function that, when called,
            creates an event processing pipeline. It keeps a pointer
            to the KVS inside of the closure. This way, each pipeline has
            its own KVS. This is the level at which we want consistency,
            want to allow sharding, etc. If two users are connected, each
            will have their own data store connection.
            '''
            print("Metadata: ")
            print(metadata)
            if metadata is not None and 'auth' in metadata:
                safe_user_id = metadata['auth']['safe_user_id']
            else:
                safe_user_id = '[guest]'
                # TODO: raise an exception.

            internal_key = make_key(func, safe_user_id, KeyStateType.INTERNAL)
            external_key = make_key(func, safe_user_id, KeyStateType.EXTERNAL)
            taskkvs = learning_observer.kvs.KVS()

            async def process_event(events):
                '''
                This is the function which processes events. It calls the event
                processor, passes in the event(s) and state. It takes
                the internal state and the external state from the
                event processor. The internal state goes into the KVS
                for use in the next call, while the external state
                returns to the dashboard.

                The external state should include everything needed
                for the dashboard visualization and exclude anything
                large or private. The internal state needs everything
                needed to continue reducing the events.
                '''
                # TODO: Think through concurrency.
                #
                # We could put this inside of a transaction, but we
                # would lose a few orders of magnitude in performance.
                #
                # We could keep this outside of a transaction, and handle
                # occasional issues.
                #
                # It's worth noting that:
                #
                # 1. We have an archival record, and we can replay if there
                #    are issues
                # 2. We keep this open on a per-session basis. The only way
                #    we might run into concurrency issues is if a student
                #    is e.g. actively editing on two computers at the same
                #    time
                # 3. If we assume e.g. occasional disconnected operation, as
                #    on a mobile device, we'll have concurrency problems no
                #    matter what. In many cases, we should handle this
                #    explicitly rather than implicitly, for example, with
                #    conflict-free replicated data type (CRDTs) or explicit
                #    merge operation
                #
                # Fun!
                #
                # But we can think of more ways we might get concurrency
                # issues in the future, once we do per-class / per-resource /
                # etc. reducers.
                #
                # * We could funnel these into a common reducer. That'd be easy
                #   enough and probably the right long-term solution
                # * We could have modules explicitly indicate where they need
                #   thread safety and transactions. That'd be easy enough.
                #
                internal_state = await taskkvs[internal_key]
                internal_state, external_state = await func(
                    events, internal_state
                )
                await taskkvs.set(internal_key, internal_state)
                await taskkvs.set(external_key, external_state)
                return external_state
            return process_event
        return wrapper_closure
    return decorator
