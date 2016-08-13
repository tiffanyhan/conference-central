#!/usr/bin/env python
import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi

from google.appengine.ext import ndb
from models import Session

class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        # TODO 1
        ConferenceApi._cacheAnnouncement()

class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )

class SetSpeakerAnnouncementHandler(webapp2.RequestHandler):
    # i think it should be post
    def post(self):
        speaker = self.request.get('speaker')
        conf_key = ndb.Key(urlsafe=self.request.get('websafeConferenceKey'))
        # check how many sessions by this speaker at given conference
        sessions = Session.query(ancestor=conf_key)
        sessions = sessions.filter(Session.speaker == speaker)
        q_count = sessions.count()
        # if more than one session,
        if q_count > 1:
            # get all sessionNames
            sessionNames = []
            for session in sessions:
                sessionNames.append(session.sessionName)
            # get the name of the conference
            conference = conf_key.get()
            conferenceName = conference.name

            # add speaker to featuredSpeakers property of conference
            conference.featuredSpeakers.append(speaker)
            conference.put()
            # pass in speaker name, session names, and conference name
            ConferenceApi._cacheSpeakerAnnouncement(speaker, sessionNames, conferenceName)

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/set_speaker_announcement', SetSpeakerAnnouncementHandler)
], debug=True)