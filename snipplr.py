import os
import threading
from xmlrpclib import ServerProxy, Error
import HTMLParser
from itertools import groupby
from operator import itemgetter

import sublime, sublime_plugin

class Worker(threading.Thread):
    """A simple worker thread that stores the task result as a parameter."""
    def __init__(self, f):
        self.f = f
        self.result = None
        threading.Thread.__init__(self)
 
    def run(self):
        self.result = self.f()

def get_api_key():
    """Loads API key from settings."""
    settings = sublime.load_settings('snipplr.sublime-settings')
    api_key = settings.get('api_key')

    if not api_key:
        sublime.error_message("No Snipplr API key found in settings")

    return api_key

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

class SnipplrInsertCommand(sublime_plugin.TextCommand):
    """Search for snippet and insert it into document at cursor position."""

    def run(self, edit):
        self.api_key = get_api_key()
        if not self.api_key:
            return

        self.server = ServerProxy("http://snipplr.com/xml-rpc.php")
        self.keywords_prompt()
        self.threads = {}
        self.snippet = None

    def keywords_prompt(self):
        self.view.window().show_input_panel("Keywords:", "", self.search, None, None)

    def search(self, keywords):
        t = Worker(lambda: self._search(keywords))
        t.start()
        self.threads['search'] = t
        handle_thread(t, 'Searching Snipplr for: '+keywords, self.search_cb)
    
    def _search(self, keywords):
        try:
            return self.server.snippet.list(self.api_key, keywords)
        except Error, v:
            if v.faultCode is 1:
                return []
            else:
                return False

    def search_cb(self):
        result = self.threads['search'].result
        if result == []:
            status('No matching snippets found')
            self.keywords_prompt()
        elif result == False:
            status('Error: Problem searching for snippets')
        else:
            # The API seems to often send multiple results for the same snippet
            # so we need to remove duplicates
            get_id = itemgetter('id')
            unique_snippets = [next(g) for a, g
                               in groupby(sorted(result, key=get_id), get_id)]
            self.search_results = unique_snippets

            result_titles = [snippet['title'] for snippet in unique_snippets]
            self.result_selection_prompt(result_titles)

    def result_selection_prompt(self, result_titles):
        status('Please select a snippet to insert')
        self.view.window().show_quick_panel(result_titles,
                                            self.result_selection_cb)

    def result_selection_cb(self, index):
        if index >= 0:
            selection = self.search_results[index]
            t = Worker(lambda: self.download(selection['id']))
            t.start()
            self.threads['download'] = t
            handle_thread(t, 'Downloading snippet (%s)' % (selection['title'],),
                          self.download_cb)

    def download(self, snippet_id):
        try:
            snippet = self.server.snippet.get(snippet_id)
            h = HTMLParser.HTMLParser()
            snippet = h.unescape(snippet['source'])
            return snippet
        except Error:
            return False

    def download_cb(self):
        snippet = self.threads['download'].result
        if not snippet == False:
            self.insert_snippet(snippet)
        else:
            status('Error: Problem downloading snippet')

    def insert_snippet(self, snippet):
        selections = self.view.sel()
        edit = self.view.begin_edit('snipplr')
        try:
            if len(selections) > 0:
                for sel in selections:
                    self.view.insert(edit, sel.begin(), snippet)
            else:
                self.view.insert(edit, 0, snippet)
        finally:
            self.view.end_edit(edit)
            status('Snippet inserted')

class SnipplrUploadCommand(sublime_plugin.TextCommand):
    """Upload currently selected text to Snipplr."""

    def run(self, edit):
        self.api_key = get_api_key()
        if not self.api_key:
            return

        regions = self.view.sel()
        if not (len(regions) > 0) or (regions[0].empty()):
            status("Error: No content selected")
            return

        self.snippet = {
            'title': None,
            'tags': None,
            'language': None,
            'source': self.view.substr(regions[0])
        }

        self.threads = {}
        self.server = ServerProxy("http://snipplr.com/xml-rpc.php")

        t = Worker(self.get_languages)
        t.start()
        self.threads['get_languages'] = t

        self.title_prompt()
            
    
    def get_languages(self):
        try:
            return self.server.languages.list()
        except Error:
            status("Error: Problem fetching languages")

    def title_prompt(self):
        self.view.window().show_input_panel("Title:", "",
                                            self.title_cb, None, None)
    
    def title_cb(self, title):
        self.snippet['title'] = title
        self.tags_prompt()

    def tags_prompt(self):
        self.view.window().show_input_panel("Tags (space delimited):", "",
                                            self.tags_cb, None, None)
    
    def tags_cb(self, tags):
        self.snippet['tags'] = tags

        # Open the language prompt once languages have downloaded
        handle_thread(self.threads['get_languages'],
                      'Downloading language list',
                      cb=self.language_prompt)

    def language_prompt(self):
        self.languages = self.threads['get_languages'].result
        self.language_names = self.languages.values()

        # Get the language of the current view
        syntax_path = self.view.settings().get('syntax')
        filename = os.path.splitext(os.path.basename(syntax_path))[0]
        # Normalise the language name to hopefully match Snipplr's
        view_language = filename.lower().replace(' ', '-')

        def sort_key(cur_lang):
            def f(lang):
                return -1 if (lang == cur_lang) else lang
            return f

        # Sort languages alphabetically, and put current view language first
        self.language_list = sorted(self.languages.keys(), key=sort_key(view_language))

        status('Please select snippet language')
        languages = [self.languages[key] for key in self.language_list]
        self.view.window().show_quick_panel(languages, self.language_cb)
    
    def language_cb(self, index):
        if index >= 0:
            self.snippet['language'] = self.language_list[index]
            t = threading.Thread(target=self.upload_snippet)
            t.start()
            handle_thread(t, 'Uploading snippet')

    def upload_snippet(self):
        snippet = self.snippet
        try:
            result = self.server.snippet.post(self.api_key, snippet['title'],
                                              snippet['source'], snippet['tags'],
                                              snippet['language'])
            if result['success'] == '1':
                status('Snippet successfully uploaded', True)
            else:
                status('Error: Problem uploading snippet', True)
        except Error:
            status('Error: Problem uploading snippet', True)