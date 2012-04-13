import threading

import sublime

class Worker(threading.Thread):
    """A simple worker thread that stores the task result as a parameter."""
    def __init__(self, f):
        self.f = f
        self.result = None
        threading.Thread.__init__(self)
 
    def run(self):
        self.result = self.f()

def status(msg, thread=False):
    """Displays a message in status bar.

    thread - set to True if displaying message from a separate thread to use
    callback.

    """
    if not thread:
        sublime.status_message(msg)
    else:
        sublime.set_timeout(lambda: status(msg), 0)

def handle_thread(thread, msg=None, cb=None, i=0, direction=1, width=8):
    """Displays an animated notification in the status bar while thread executes.

    msg - message to be displayed in status bar.
    cb - optional callback to be executed when thread completes.

    """
    if thread.is_alive():
        next = i + direction
        if next > width:
            direction = -1
        elif next < 0:
            direction = 1
        bar = [' ']*(width + 1)
        bar[i] = '='
        i += direction
        status('%s [%s]' % (msg, ''.join(bar)))
        sublime.set_timeout(lambda: handle_thread(thread, msg, cb, i,
                            direction, width), 100)
    else:
        cb()