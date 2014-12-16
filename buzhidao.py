import os
import urllib
import logging
import datetime
import math
import cgi
import re

from google.appengine.api import images
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers


import jinja2
import webapp2

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

#separate the vote kind to avoid 
# confliction in ancestor query
class QVote(ndb.Model):
    user = ndb.UserProperty()
    up = ndb.BooleanProperty()

class AVote(ndb.Model):
    user = ndb.UserProperty()
    up = ndb.BooleanProperty()

class Question(ndb.Model):
    """Models an individual Guestbook entry."""
    author = ndb.UserProperty()
    title = ndb.StringProperty(indexed=False)
    content = ndb.StringProperty(indexed=False)
    created_date = ndb.DateTimeProperty(auto_now_add=True)
    modified_date = ndb.DateTimeProperty()
    tags = ndb.StringProperty(repeated=True)

class Answer(ndb.Model):
    author = ndb.UserProperty()
    content = ndb.StringProperty(indexed=False)
    created_date = ndb.DateTimeProperty(auto_now_add=True)
    modified_date = ndb.DateTimeProperty()


def url_repl(m):
    ext = m.group(1)
    if ext in ['.png', '.jpg', '.gif']:
        return "<img src='%s'>" % m.group(0)
    else:
        return "<a href='%s'>%s</a>" % (m.group(0), m.group(0))

def parse_content(content):

    return re.sub(r'[a-zA-Z0-9]+://(?:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+@)?(?:[a-zA-Z0-9.-]+\.[A-Za-z]{2,4})(?::[0-9]+)?(?:/[^ \.]*)?(\.[^ ]*)?(?:/[^ ]*)?', url_repl, content)


class MainPage(webapp2.RequestHandler):

    def get(self):

        page_size = 2

        page = self.request.get('page')
        tag = self.request.get('tag')

        if not page:
            page = 0
        else:
            page = int(page)

        if tag:
            question_query = Question.query(Question.tags==tag, ancestor=ndb.Key("Questions", "0")).order(-Question.created_date)
        else:
            question_query = Question.query(ancestor=ndb.Key("Questions", "0")).order(-Question.created_date)

        n_page = int(math.ceil(question_query.count() / float(page_size)))
        questions = question_query.fetch(page_size, offset=page*page_size)

    
        user = users.get_current_user()

        file_upload_url = None

        if user:
            url = users.create_logout_url(self.request.uri)
            url_linktext = 'Logout'
            file_upload_url = blobstore.create_upload_url('/upload')
        else:
            url = users.create_login_url(self.request.uri)
            url_linktext = 'Login'

        template_values = {
            'parse_content': parse_content,
            'tag': tag,
            'user': user,
            'page': page,
            'file_upload_url': file_upload_url,
            'n_page': n_page,
            'questions': questions,
            'url': url,
            'url_linktext': url_linktext
        }

        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render(template_values))

class AddQuestion(webapp2.RequestHandler):
    def post(self):
        # We set the same parent key on the 'Greeting' to ensure each Greeting
        # is in the same entity group. Queries across the single entity group
        # will be consistent. However, the write rate to a single entity group
        # should be limited to ~1/second.

        user = users.get_current_user()

        if user:
            question = Question(author=user, parent=ndb.Key("Questions", "0"))
            question.title = self.request.get('title')
            question.content = cgi.escape(self.request.get('content'))
            q_tags = self.request.get('tags').split(r',')
            question.tags = q_tags

            question.put()

        else:
            self.redirect(users.create_login_url())
    
        self.redirect('/')


def get_vote(cls, entity):
    vote_query = cls.query(ancestor=entity.key)
    count = 0
    for vote in vote_query:
        if vote.up:
            count = count+1
        else:
            count = count-1

    return count


class ShowQuestion(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()
        question = ndb.Key(urlsafe=self.request.get('qid')).get()

        q_vote = get_vote(QVote, question)

        # Use ancestor query to achieve storng consistency
        answer_query = Answer.query(ancestor=question.key)

        answers = []

        for ans in answer_query:
            a_vote = get_vote(AVote, ans)
            answers.append({
                'vote': a_vote,
                'entity': ans
                })

        template_values = {
            'parse_content': parse_content,
            'q_vote': q_vote,
            'user': user,
            'question': question,
            'answers': answers
        }

        template = JINJA_ENVIRONMENT.get_template('question.html')
        self.response.write(template.render(template_values))

class VoteIt(webapp2.RequestHandler):
    def post(self):
        user = users.get_current_user()

        if user:
            key = ndb.Key(urlsafe=self.request.get('id'))
            cls = QVote

            if key.kind() == "Answer":
                cls = AVote

            vote = cls.query(cls.user==user, ancestor=key).get()

            if not vote:
                vote = cls(user=user, parent=key)

            if self.request.get('up'):
                vote.up = True
            else:
                vote.up = False

            vote.put()
        else:
            self.redirect(users.create_login_url())

class AnswerQuestion(webapp2.RequestHandler):
    def post(self):
        user = users.get_current_user()

        if user:
            q_key = ndb.Key(urlsafe=self.request.get('qid'))

            answer = Answer(author=user, parent=q_key)
            answer.content = cgi.escape(self.request.get('content'));

            answer.put()
            self.redirect("/question?qid="+q_key.urlsafe())
        else:
            self.redirect(users.create_login_url())

class EditQuestion(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()

        if user:
            question = ndb.Key(urlsafe=self.request.get('qid')).get()

            template_values = {
                'question': question
            }

            template = JINJA_ENVIRONMENT.get_template('edit_question.html')
            self.response.write(template.render(template_values))

        else:
            self.redirect(users.create_login_url())

    def post(self):
        user = users.get_current_user()

        if user:
            question = ndb.Key(urlsafe=self.request.get('qid')).get()
            
            question.title = self.request.get('title')
            question.content = cgi.escape(self.request.get('content'))
            question.modified_date = datetime.datetime.now()

            q_tags = self.request.get('tags').split(r',')
            question.tags = q_tags

            question.put()

            self.redirect("/question?qid="+question.key.urlsafe())

        else:
            self.redirect(users.create_login_url())


class EditAnswer(webapp2.RequestHandler):
    def get(self):
        user = users.get_current_user()

        if user:
            answer = ndb.Key(urlsafe=self.request.get('aid')).get()

            template_values = {
                'answer': answer
            }

            template = JINJA_ENVIRONMENT.get_template('edit_answer.html')
            self.response.write(template.render(template_values))

        else:
            self.redirect(users.create_login_url())

    def post(self):
        user = users.get_current_user()

        if user:
            answer = ndb.Key(urlsafe=self.request.get('aid')).get()
            
            
            answer.content = cgi.escape(self.request.get('content'))
            answer.modified_date = datetime.datetime.now()

            answer.put()

            self.redirect("/question?qid="+answer.key.parent().urlsafe())

        else:
            self.redirect(users.create_login_url())

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        upload_files = self.get_uploads('file')
        blob_info = upload_files[0]

        template_values = {
            'url': images.get_serving_url(blob_info)
        }

        template = JINJA_ENVIRONMENT.get_template('uploaded.html')
        self.response.write(template.render(template_values))

class GetRss(webapp2.RequestHandler):

    def get(self):
        question = ndb.Key(urlsafe=self.request.get('qid')).get()

        # Use ancestor query to achieve storng consistency
        answer_query = Answer.query(ancestor=question.key)

        answers = [ ans for ans in answer_query]

        template_values = {
            'url': self.request.host_url + "/question?" + self.request.query_string,
            'question': question,
            'answers': answers
        }

        self.response.content_type="text/xml"
        template = JINJA_ENVIRONMENT.get_template('question.xml')
        self.response.write(template.render(template_values))




application = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/ask', AddQuestion),
    ('/question', ShowQuestion),
    ('/rss', GetRss),
    ('/vote', VoteIt),
    ('/answer', AnswerQuestion),
    ('/edit_question', EditQuestion),
    ('/edit_answer', EditAnswer),
    ('/upload', UploadHandler)
], debug=True)