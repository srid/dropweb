from os import path
from datetime import datetime

import markdown

from google.appengine.ext import webapp, db
from google.appengine.ext.webapp import util
from google.appengine.api.urlfetch import fetch
from google.appengine.api import users
from google.appengine.ext.webapp import template


class MyDropboxAccount(db.Model):
    
    diary_url = db.StringProperty(required=True) # 'http://dl.dropbox.com/u/87045/diary/%s.txt'
    encryption_key = db.StringProperty()
    
    @staticmethod
    def get():
        results = list(MyDropboxAccount.all())
        if not results:
            raise RuntimeError('no dropbox account setup')
        elif len(results) == 1:
            return results[0]
        else:
            raise RuntimeError('multiple accounts found')
            

class DropboxPublicPage(db.Model):
    
    name = db.StringProperty(required=True)
    
    # actual content of the file
    data = db.BlobProperty()     
    # decrypted content of the file (vim -x)
    text = db.TextProperty()
    # html version of text
    html = db.TextProperty()
    # dropbox etag for this url
    etag = db.StringProperty()
    
    # Meta information from Markdown
    title = db.StringProperty()
    tags = db.StringListProperty()
    date_published = db.DateProperty()
    
    @staticmethod
    def get_page(name):
        """Return an instance of DropboxPublicPage for the given dropbox URL
        
        Transparently handle updating new copies from Dropbox, if any. This is
        done using the fact that Dropbox alters the URL etag if there is any
        update to the content.
        """
        acct = MyDropboxAccount.get()
        url = acct.diary_url % name
        
        results = list(DropboxPublicPage.all().filter('name =', name))
        if not results:
            page = DropboxPublicPage(name=name)
        elif len(results) == 1:
            page = results[0]
        else:
            raise RuntimeError, 'duplicate page objects for url: %s' % url
        
        # refetch if etag was updated
        if not page.etag or check_fetch(url, method='HEAD').headers['etag'] != page.etag:
            response = check_fetch(url)
            page._set_content(response.content, acct)
            page.etag = response.headers['etag']
            page.put()
        
        return page
      
    def _set_content(self, data, acct):
        """Set page content (raw)"""
        # decrypt vim encrypted file
        if data.startswith('VimCrypt~01!'):
            text = vim_decrypt(data, acct.encryption_key)
        else:
            text = data
            
        self.data = data
        self.text = text
        
        md = create_md()
        self.html = md.convert(self.text)
        
        # update Meta
        meta = md.Meta
        self.title = meta['title'][0]
        self.tags = meta['tags'][0].replace(',', ' ').split()
        if 'datepublished' in meta:
            self.date_published = datetime.strptime(
                meta['datepublished'][0],
               '%b %d, %Y').date()
        else:
            # wiki page, not a 'published' diary entry
            self.date_published = None
        
    def is_private(self):
        return self.text != self.data # vim encrypted?
    
    def md_convert(self):
        md = create_md()
        return md.convert(self.text), md.Meta
    
    
class FetchError(Exception):
    def __init__(self, response):
        self.response = response
        Exception.__init__(self)
def check_fetch(*args, **kwargs):
    """fetch() that raises exception on non-200 http codes"""
    response = fetch(*args, **kwargs)
    if response.status_code == 200:
        return response
    else:
        raise FetchError(response)
        
    
def create_md():
    return markdown.Markdown(extensions = [
      'headerid(forceid=True, level=2)', # start from H2 level
      'footnotes',
      'meta'])
    
    
def vim_decrypt(data, key):
    zd = _ZipDecrypter(key)
    return ''.join([zd(c) for c in data[12:]])



class DropwebRequestHandler(webapp.RequestHandler):
  
    def admin_only(self):
        user = users.get_current_user()
        is_admin = users.is_current_user_admin()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
        elif not is_admin:
            self.error(403)
            self.render_template('error.html', dict(
              msg='sorry, only the website owner can access this page'))
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
            template.render(
              path.join(path.dirname(__file__), 'templates', tmplname),
              tmplargs)
        )
        
        
class DropboxAccountHandler(DropwebRequestHandler):
  
    def get(self):
        if not self.admin_only(): return
        
        url = self.request.get('diary_url')
        key = self.request.get('encryption_key')
        acct = MyDropboxAccount(diary_url=url, encryption_key=key)
        acct.put()
        self.render_template('error.html', dict(
          msg = 'Set dropbox account details successfully'))
    

class MainHandler(DropwebRequestHandler):
  
    def get(self):
        pages = [p for p in DropboxPublicPage.all() if not p.is_private()]
        # sort by title, as not all pages have published_date
        pages.sort(key=lambda page: page.title)
        
        # Split general and tech posts based on tag 'tech'.
        # Purpose: followers who does not care about my programming related
        # posts can simply follow the 'general' content
        sections = {}
        general_posts = sections['General'] = dict(pages=[], embed=EMBED_MY_BUZZ)
        tech_posts = sections['Technology & Programming'] = dict(pages=[], embed=EMBED_MY_TWITTER)
        
        for page in pages:
            if 'tech' in page.tags:
                tech_posts['pages'].append(page)
            else:
                general_posts['pages'].append(page)
        
        self.render_template('main.html', dict(sections=sections))


class PageHandler(DropwebRequestHandler):
  
    def get(self, name):
        try:
            page = DropboxPublicPage.get_page(name)
        except FetchError, e:
            html = 'non-200 status: %s' % e.response.status_code
            self.render_template('error.html', dict(
              msg='non-200 status: %s' % e.response.status_code))
            self.error(e.response.status_code)
        else:
            if page.is_private():
                if not self.admin_only():
                    return
            self.render_template('page.html', dict(page=page))
     

# copied from Python2.6's zipfile.py   
class _ZipDecrypter:
    """Class to handle decryption of files stored within a ZIP archive.

    ZIP supports a password-based form of encryption. Even though known
    plaintext attacks have been found against it, it is still useful
    to be able to get data out of such a file.

    Usage:
        zd = _ZipDecrypter(mypwd)
        plain_char = zd(cypher_char)
        plain_text = map(zd, cypher_text)
    """

    def _GenerateCRCTable():
        """Generate a CRC-32 table.

        ZIP encryption uses the CRC32 one-byte primitive for scrambling some
        internal keys. We noticed that a direct implementation is faster than
        relying on binascii.crc32().
        """
        poly = 0xedb88320
        table = [0] * 256
        for i in range(256):
            crc = i
            for j in range(8):
                if crc & 1:
                    crc = ((crc >> 1) & 0x7FFFFFFF) ^ poly
                else:
                    crc = ((crc >> 1) & 0x7FFFFFFF)
            table[i] = crc
        return table
    crctable = _GenerateCRCTable()

    def _crc32(self, ch, crc):
        """Compute the CRC32 primitive on one byte."""
        return ((crc >> 8) & 0xffffff) ^ self.crctable[(crc ^ ord(ch)) & 0xff]

    def __init__(self, pwd):
        self.key0 = 305419896
        self.key1 = 591751049
        self.key2 = 878082192
        for p in pwd:
            self._UpdateKeys(p)

    def _UpdateKeys(self, c):
        self.key0 = self._crc32(c, self.key0)
        self.key1 = (self.key1 + (self.key0 & 255)) & 4294967295
        self.key1 = (self.key1 * 134775813 + 1) & 4294967295
        self.key2 = self._crc32(chr((self.key1 >> 24) & 255), self.key2)

    def __call__(self, c):
        """Decrypt a single character."""
        c = ord(c)
        k = self.key2 | 2
        c = c ^ (((k * (k^1)) >> 8) & 255)
        c = chr(c)
        self._UpdateKeys(c)
        return c

def main():
  application = webapp.WSGIApplication([
    ('/acct', DropboxAccountHandler),
    ('/(.+)', PageHandler),
    ('/', MainHandler),
  ], debug=True)
  util.run_wsgi_app(application)


# get this from http://www.buzzcounter.net/
EMBED_MY_BUZZ = r'''
<div id="buzzwidget"><script type="text/javascript"> if (typeof jQuery == 'undefined') { document.write('<script type="text/javascript" language="javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.4/jquery.min.js"><\/script>'); }</script>
<script type="text/javascript" language="javascript" src="http://www.buzzcounter.net/widget/107514687808578919461?background=fcfcfc&buzzbackground=fcfcfc&text=333333&smalltext=c0c0c0&link=17375e"></script><script type="text/javascript">$.Widget.get();</script><div id="buzzwidget-footer"><a id="buzz-logo" href="http://buzz.google.com/">Google</a><a id="buzzcounter-logo" href="http://www.buzzcounter.net/">Google Buzz</a></div></div>
<script type="text/javascript">$.Widget.set();</script>
'''

# get this from http://twitter.com/goodies/widget_profile
EMBED_MY_TWITTER = r'''
<script src="http://widgets.twimg.com/j/2/widget.js"></script>
<script>
new TWTR.Widget({
  version: 2,
  type: 'profile',
  rpp: 4,
  interval: 6000,
  width: 'auto',
  height: 300,
  theme: {
    shell: {
      background: '#fcfcfc',
      color: '#000000'
    },
    tweets: {
      background: '#fcfcfc',
      color: '#000000',
      links: ''
    }
  },
  features: {
    scrollbar: false,
    loop: false,
    live: false,
    hashtags: true,
    timestamp: true,
    avatars: false,
    behavior: 'all'
  }
}).render().setUser('sridhr').start();
</script>
'''


if __name__ == '__main__':
  main()
