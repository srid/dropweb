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

import markdown

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.api.urlfetch import fetch
from google.appengine.api import users
from google.appengine.ext.webapp import template


md_url = 'http://dl.dropbox.com/u/87045/diary/%s.txt'

def create_md():
    return markdown.Markdown(extensions = [
      'headerid(forceid=True, level=2)', # start from H2 level
      'footnotes',
      'meta'])


class DropwebRequestHandler(webapp.RequestHandler):
  
    def admin_only(self):
        user = users.get_current_user()
        is_admin = users.is_current_user_admin()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
        elif not is_admin:
            self.error(403)
            self.render_template('index.html', dict(
              content='sorry, not authorized', meta=None))
        else:
            return True

    def render_template(self, tmplname, tmplargs):
        tmplargs['user'] = user = users.get_current_user()
        if user:
            tmplargs['authlink'] = (
                'logout %s' % user.nickname(),
                users.create_logout_url(self.request.uri))
        else:
            tmplargs['authlink'] = (
                'login',
                users.create_login_url(self.request.uri))
            
        self.response.out.write(
            template.render(path.join(path.dirname(__file__), tmplname), tmplargs)
        )
    

class MainHandler(DropwebRequestHandler):
  
    def get(self):
        self.render_template('index.html', dict(
            content = 'Under construction',
            meta = None
        ))


class PageHandler(DropwebRequestHandler):
  
    def get(self, name):
        md = create_md()
        url = md_url % name
        urlresp = fetch(url)
        if urlresp.status_code == 200:
            content = md.convert(fetch(url).content)
            meta = md.Meta
            error = False
            
            if 'access' not in meta or meta['access'][0].lower() != 'public':
                if not self.admin_only():
                    return
        else:
            content = 'non-OK status: %s' % urlresp.status_code
            meta = None
            error = True
            
        self.render_template(
            'index.html', dict(content=content, meta=meta))
        
        if error: self.error(urlresp.status_code)


def main():
  application = webapp.WSGIApplication([
    ('/(.+)', PageHandler),
    ('/', MainHandler),
  ], debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
