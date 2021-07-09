'''
This pipeline extracts high-level features from writing process data.
It just routes to smaller pipelines. Currently that's:
1) Time-on-task
2) Reconstruct text (+Deane graphs, etc.)
'''
from learning_observer.stream_analytics.helpers import kvs_pipeline
import writing_observer.reconstruct_doc

# How do we count the last action in a document? If a student steps away
# for hours, we don't want to count all those hours.
#
# We might e.g. assume a one minute threshold. If students are idle
# for more than a minute, we count one minute. If less, we count the
# actual time spent. So if a student goes away for an hour, we count
# that as one minute. This threshold sets that maximum. For debugging,
# a few seconds is convenient. For production use, 60-300 seconds (or
# 1-5 minutes) might be more reasonable.
#
# In edX, for time-on-task calculations, the exact threshold had a
# surprisingly small impact on any any sort of interpretation
# (e.g. all the numbers would go up/down 20%, but behavior was
# substantatively identical).

# Should be 60-300 in prod. 5 seconds is nice for debugging
TIME_ON_TASK_THRESHOLD = 5


@kvs_pipeline()
async def time_on_task(event, internal_state):
    '''
    This adds up time intervals between successive timestamps. If the interval
    goes above some threshold, it adds that threshold instead (so if a student
    goes away for 2 hours without typing, we only add e.g. 5 minutes if
    `time_threshold` is set to 300.
    '''
    if internal_state is None:
        internal_state = {
            'saved_ts': None,
            'total-time-on-task': 0
        }
    last_ts = internal_state['saved_ts']
    internal_state['saved_ts'] = event['server']['time']

    # Initial conditions
    if last_ts is None:
        last_ts = internal_state['saved_ts']
    if last_ts is not None:
        delta_t = min(
            TIME_ON_TASK_THRESHOLD,               # Maximum time step
            internal_state['saved_ts'] - last_ts  # Time step
        )
        internal_state['total-time-on-task'] += delta_t
    return internal_state, internal_state

def internal_state_setup(event, internal_state, initial_doc_state):
    '''
    This function sets up the internal state variables used by some of the pipeline
    functions, specifically, the hierarchy that tracks the user, document, and frame
    within which an event happens.
    '''

    # Use the safe_user_id field from metadata
    safe_user_id = event['metadata']['auth']['safe_user_id']

    # Use the doc id from the event as the primary key
    doc_id = event['client']['doc_id']

    # Track frame ids
    frameid = None
    if 'frameindex' in event['client']:
        frameid = event['client']['frameindex']

    # Initialize internal_state so that it has key-value pairs for each doc_id + frameid combination
    # for the visible feature. This is because Google Docs generates a separate visibilitystate event
    # for each frame document in a Google Doc.
    if internal_state is None:
        internal_state = {}

    if safe_user_id not in internal_state:
        internal_state[safe_user_id] = {}

    if doc_id not in internal_state[safe_user_id]:
        internal_state[safe_user_id][doc_id] = initial_doc_state

    if 'frameset' in internal_state[safe_user_id][doc_id] and frameid not in internal_state[safe_user_id][doc_id]['frameset'] and frameid is not None:
        frameset = {}
        internal_state[safe_user_id][doc_id]['frameset'][frameid] = frameset
    return (safe_user_id, doc_id, frameid, internal_state)

@kvs_pipeline()
async def attention_state(event, internal_state):
    '''
    This function tracks events that let us know whether we are currently in an active session
    or in some other state. Visible means that the browser window is visible in the broser and the
    browser has not been minimized. in_focus means that the window containing the document has received focus.
    '''
    # Do not calculate attentions states for non-document events like warnings
    if 'doc_id' not in event['client']:
        return (internal_state,internal_state)

    initial_doc_state = {
        "in_focus": True,
        "frameset": {
             "0": {
                 "visible": True
             },
             "1": {
                 "visible": True
             },
             "2": {
                 "visible": True
              },
             "3": {
                 "visible": True
              }
        }
    }

    (safe_user_id, doc_id, frameid, internal_state) = internal_state_setup(event, internal_state, initial_doc_state)

    internal_state[safe_user_id][doc_id]['saved_time'] = event['client']['ts'] / 1000

    # Track visibility using visibilitychange
    if event['client']['event']=='visibility'  \
        and event['client']['visibility']['type'] == "visibilitychange" \
        and frameid is not None:
        if internal_state[safe_user_id][doc_id]['frameset'][frameid]['visible']:
            internal_state[safe_user_id][doc_id]['frameset'][frameid]['visible'] = False
        else:
            internal_state[safe_user_id][doc_id]['frameset'][frameid]['visible'] = True

    # Visibilitychange has one hole in it -- when a student alt-tabs to another page. This
    # is not necessarily a visibility change -- that depends on window size. But alt tab doesn't
    # tell us enough, so we need to track focusin / focusout. Focusin implies visiblity, though
    # focusout doesn't guarantee the screen is hidden.
    if event['client']['event'] == "attention" and event['client']['attention']['type'] == 'focusin':
        internal_state[safe_user_id][doc_id]['in_focus'] = True
    elif event['client']['event'] =="attention" and event['client']['attention']['type'] == 'focusout':
        internal_state[safe_user_id][doc_id]['in_focus'] = False
    elif event['client']['event'] == 'keystroke' or event['client']['event'] == 'mouseclick':
        internal_state[safe_user_id][doc_id]['in_focus'] = True
        for fid in internal_state[safe_user_id][doc_id]['frameset']:
            internal_state[safe_user_id][doc_id]['frameset'][fid]['visible'] = True

    print(internal_state)

    return internal_state, internal_state


@kvs_pipeline()
async def track_open_comments_by_document(event, internal_state):
    '''
    This pipeline is intended to be used to poll user/document/comment relationships,
    for instance, when a teacher wants to know which students have made how many comments
    on their fellow students' work during the current session.
    '''

    if internal_state is None:
        internal_state = {
        }
 
    if 'doc_id' not in event['client'] or 'type' not in event['client']:
        return internal_state, internal_state
   
    (safe_user_id, doc_id, frameid, internal_state) = internal_state_setup(event, internal_state, {})

    if event['client']['event'] == "attention" and event['client']['attention']['type'] == 'focusin':
        internal_state[safe_user_id][doc_id]['in_focus'] = True
    elif event['client']['event'] =="attention" and event['client']['attention']['type'] == 'focusout':
        internal_state[safe_user_id][doc_id]['in_focus'] = False
    elif event['client']['type'] == 'type-input':
        internal_state[safe_user_id][doc_id]['last_input_id'] = event['client']['parentID']
        internal_state[safe_user_id][doc_id]['last_input'] = event['client']['value']
        internal_state[safe_user_id][doc_id]['last_input_ts'] = event['client']['ts'] 
        if 'first_input_ts' not in internal_state[safe_user_id][doc_id]:
            internal_state[safe_user_id][doc_id]['first_input_ts'] = event['client']['ts']
    elif event['client']['type'] == 'clear-input':
        internal_state[safe_user_id][doc_id]['last_input'] = ''
    elif event['client']['type'] == 'add-comment' or event['client']['type'] == 'edit-comment':
        comment_id = internal_state[safe_user_id][doc_id]['last_input_id']
        internal_state[safe_user_id][doc_id]['comments']={}
        if comment_id not in internal_state[safe_user_id][doc_id]['comments']:
            internal_state[safe_user_id][doc_id]['comments']={}
            internal_state[safe_user_id][doc_id]['comments'][comment_id]={}
        if internal_state[safe_user_id][doc_id]['last_input']!='':
           internal_state[safe_user_id][doc_id]['comments'][comment_id]['comment_text'] = internal_state[safe_user_id][doc_id]['last_input'] 
        else:
            internal_state[safe_user_id][doc_id]['comments'][comment_id]['comment_text'] = None
        if 'first_input_ts' not in internal_state[safe_user_id][doc_id]['comments'][comment_id]:
            internal_state[safe_user_id][doc_id]['comments'][comment_id]['first_input_ts'] = event['client']['ts']
        internal_state[safe_user_id][doc_id]['comments'][comment_id]['last_input_ts'] = event['client']['ts']
    elif event['client']['type'] == 'add-reply':
        reply_id = internal_state[safe_user_id][doc_id]['last_input_id'] 
        internal_state[safe_user_id][doc_id]['replies']={}
        if comment_id not in internal_state[safe_user_id][doc_id]['replies']:
            internal_state[safe_user_id][doc_id]['replies']={}
            internal_state[safe_user_id][doc_id]['replies'][reply_id]={}
        if internal_state[safe_user_id][doc_id]['last_input']!='':
           internal_state[safe_user_id][doc_id]['replies'][reply_id]['text'] = internal_state[safe_user_id][doc_id]['last_input'] 
        else:
            internal_state[safe_user_id][doc_id]['replies'][comment_id]['text'] = None
        if 'first_input_ts' not in internal_state[safe_user_id][doc_id]['replies'][comment_id]:
            internal_state[safe_user_id][doc_id]['replies'][comment_id]['first_input_ts'] = event['client']['ts']
        internal_state[safe_user_id][doc_id]['replies'][comment_id]['last_input_ts'] = event['client']['ts']

    # TO-DO: We need to purge users who aren't connected and documents that aren't open
    # We also need to decide what to do about old comments from before a reload -- the way
    # we are getting comment text depends on someone actually making a change to the text.
      
    print(internal_state)
    return internal_state, internal_state


@kvs_pipeline()
async def baseline_typing_speed(event, internal_state):
    '''
    This function calculates baseline typing speed (characters per second for alphanumeric characters after
    the first character in a word). In our research results so far, this is an extremely reliable metric.
    Excluding word initial characters and nonalphanumeric keys eliminates pauses likely to be associated
    with most forms of metacognitive planning and deliberation, and so provides a relatively clean
    measure of typing speed. The best measure is probably median log latencies, but that would be harder
    to report to users.
    '''
    if 'doc_id' not in event['client'] \
        or ('keystroke' in event['client'] and event['client']['keystroke']['type'] != 'keydown') \
        or 'keystroke' in event['client'] and event['client']['keystroke']['keyCode']==16:
        return internal_state, internal_state

    if internal_state is None:
        internal_state = {}

    initial_doc_state = {
        "frameset": {
            "0": {
                    'saved_time': None,
                    'saved_keycode': None,
                    'total_inword_typing_time': 0,
                    'nWordInternalKeystrokes': 0,
                    'meanCharactersPerSecond': 0.0
            },
            "1": {
                    'saved_time': None,
                    'saved_keycode': None,
                    'total_inword_typing_time': 0,
                    'nWordInternalKeystrokes': 0,
                    'meanCharactersPerSecond': 0.0
            },
            "2": {
                    'saved_time': None,
                    'saved_keycode': None,
                    'total_inword_typing_time': 0,
                    'nWordInternalKeystrokes': 0,
                    'meanCharactersPerSecond': 0.0
            },
            "3": {
                    'saved_time': None,
                    'saved_keycode': None,
                    'total_inword_typing_time': 0,
                    'nWordInternalKeystrokes': 0,
                    'meanCharactersPerSecond': 0.0
            }
        }
    }

    (safe_user_id, doc_id, frameid, internal_state) = internal_state_setup(event, internal_state, initial_doc_state)

    if frameid is None:
        return internal_state, internal_state

    if 'event_type' in event['client'] and 'keystroke' in event['client']:
        print(event['client']['event_type'])
        print(event['client']['keystroke']['altKey'])
        print(event['client']['keystroke']['ctrlKey'])
        print(event['client']['keystroke']['keyCode'])
        print(event['client']['keystroke']['key'])

    if 'saved_time' in internal_state[safe_user_id][doc_id]['frameset'][frameid]:
        last_time = internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time']
    else:
        last_time = None
    internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time'] = event['client']['ts'] / 1000

    if 'saved_keycode' in internal_state[safe_user_id][doc_id]['frameset'][frameid]:
        last_keycode = internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_keycode']

    # Identify in-word keypresses.
    # Exclude events that aren't keypresses.
    # Exclude keypresses combined with the alt or ctrl keys
    # Exclude nonalphanumeric characters, defined as anything other than A-Z, a-z, 0-9, or hyphen
    # (a better definion would allow internal apostrophes, and allow different types of
    # keycodes for variants of hyphen or apostrophe, but that's too complex to address
    # in the first instance.)
    # Exclude the first keypress after an excluded event

    if 'event_type' in event['client'] and event['client']['event_type'] == 'keystroke' \
        and not event['client']['keystroke']['altKey'] and not event['client']['keystroke']['ctrlKey']:
        if (event['client']['keystroke']['keyCode'] > 47 and event['client']['keystroke']['keyCode'] < 91) \
            or event['client']['keystroke']['keyCode'] == 173:
            internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_keycode'] = event['client']['keystroke']['keyCode']
            if last_keycode is not None:
                internal_state[safe_user_id][doc_id]['frameset'][frameid]['nWordInternalKeystrokes'] += 1
        else:
            internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_keycode'] = None

    # Reset saved keycode to None for non alphanumeric events.
    else:
        internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_keycode'] = None

    # Initial conditions
    if last_time is None:
        last_time = internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time']
    if last_keycode is None and 'saved_keycode' in internal_state[safe_user_id][doc_id]['frameset'][frameid]:
        last_keycode = internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_keycode']

    # Typing speed calculation based on assumption that events are reported in order.
    # last_time None will exclude nonalphanumerics.
    # requiring keypress==down will make sure we only do interkey interval statistics.
    # and we want to avoid any crazies from out of order events that would give us.
    # negative times and thereby corrupt the speed measure.
    if last_time is not None and last_keycode is not None and last_time <= internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time']:
        delta_t = min(
            TIME_ON_TASK_THRESHOLD,
            # Maximum time step
            internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time'] - last_time  # Time step
        )
        internal_state[safe_user_id][doc_id]['frameset'][frameid]['total_inword_typing_time'] += delta_t
        internal_state[safe_user_id][doc_id]['frameset'][frameid]['meanCharactersPerSecond'] = internal_state[safe_user_id][doc_id]['frameset'][frameid]['nWordInternalKeystrokes'] / internal_state[safe_user_id][doc_id]['frameset'][frameid]['total_inword_typing_time']
        # print('Total typing time: ' + str(internal_state[safe_user_id][doc_id]['frameset'][frameid]['total_inword_typing_time']))
        # print('Current mean typing speed: ' + str(internal_state[safe_user_id][doc_id]['frameset'][frameid]['meanCharactersPerSecond']))

    # Report out of order events
    # if last_time is not None and last_time > internal_state[safe_user_id][doc_id]['frameset'][frameid]['saved_time']:
    #    print('Event at ' + str(last_time) + 'appeared out of order.')

    print(internal_state)

    return internal_state, internal_state


@kvs_pipeline()
async def reconstruct(event, internal_state):
    '''
    This is a thin layer to route events to `reconstruct_doc` which compiles
    Google's deltas into a document. It also adds a bit of metadata e.g. for
    Deane plots.
    '''
    # print(internal_state)

    internal_state = writing_observer.reconstruct_doc.google_text.from_json(
        json_rep=internal_state)
    if event['client']['event'] == "google_docs_save":
        bundles = event['client']['bundles']
        for bundle in bundles:
            internal_state = writing_observer.reconstruct_doc.command_list(
                internal_state, bundle['commands']
            )
    elif event['client']['event'] == "document_history":
        change_list = [
            i[0] for i in event['client']['history']['changelog']
        ]
        internal_state = writing_observer.reconstruct_doc.command_list(
            writing_observer.reconstruct_doc.google_text(), change_list
        )
    state = internal_state.json
    print(state)
    return state, state


async def pipeline(metadata):
    '''
    We pass the event through all of our analytic pipelines, and
    combine the results into a common state-of-the-universe to return
    for display in the dashboard.
    '''
    processors = [time_on_task(metadata), reconstruct(metadata), attention_state(metadata), baseline_typing_speed(metadata), track_open_comments_by_document(metadata)]
    # processors = [time_on_task(metadata), reconstruct(metadata), attention_state(metadata), baseline_typing_speed(metadata)]

    async def process(event):
        external_state = {}
        if processors is not None:
            for processor in processors:
                external_state.update(await processor(event))
        return external_state
    return process
