"""Model-aware bounded response-depth profiles; never expose internal deliberation."""
import re
from friday.models.profile import InferenceProfile
from zorvyq.security import SPECIALIST

MODES = ('Short', 'Medium', 'Deep Analysis')
MODE_LENGTH = {'Short':'Short','Medium':'Balanced','Deep Analysis':'Detailed'}
LENGTH_MODE = {v:k for k,v in MODE_LENGTH.items()}

def profile(model, mode, question=''):
    if model not in ('qwen3:4b',SPECIALIST) or mode not in MODES:
        raise ValueError('Unsupported model or response depth.')
    if re.search(r'\b(?:in detail|everything in detail|comprehensive|full explanation)\b',question,re.I):
        mode = 'Deep Analysis'
    # Foundation-Sec advertises completion only. These are final-answer depth
    # preferences, not a claim of hidden reasoning quality or a shared think API.
    return InferenceProfile(num_ctx=8192, num_predict={'Short':768,'Medium':1024,'Deep Analysis':2048}[mode],
        timeout_seconds=450 if mode=='Deep Analysis' else 300, temperature=.3,
        max_history_messages=0, think=False, require_complete=True)
