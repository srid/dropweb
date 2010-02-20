#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from os import path
from markdown import markdown

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api.urlfetch import fetch
from google.appengine.ext.webapp import template


md_url = 'http://dl.dropbox.com/u/87045/diary.txt'


def to_html(rest):
    """Convert reST formatted body to HTML with <h2> as starting heading"""
    return markdown(rest, extensions=['headerid(forceid=True)',
                                      'footnotes',
                                      'meta'])
        
        
class MainHandler(webapp.RequestHandler):

  def get(self):
    self.response.out.write(
      template.render(path.join(path.dirname(__file__), 'index.html'), dict(
        md_url = md_url,
        content = to_html(fetch(md_url).content)
      )))


def main():
  application = webapp.WSGIApplication([('/', MainHandler)],
                                       debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
