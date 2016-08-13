#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import logging

from datetime import datetime
import json
import os
import time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import urlfetch
from google.appengine.ext import ndb
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import TeeShirtSize

from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms

from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionQueryForm
from models import SessionQueryForms

from models import BooleanMessage
from models import ConflictException
from models import StringMessage

from settings import WEB_CLIENT_ID

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID

MEMCACHE_ANNOUNCEMENTS_KEY = 'RECENT ANNOUNCEMENTS'
MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY = 'SPEAKER ANNOUNCEMENTS'

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

CONF_FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

# TODO: define allowed session filters
SESS_FIELDS = {
            'SESSION_NAME': 'sessionName',
            'HIGHLIGHTS': 'highlights',
            'SPEAKER': 'speaker',
            'DURATION': 'duration',
            'TYPE_OF_SESSION': 'typeOfSession',
            'DATE_TIME': 'dateTIme',
            }

# ResourceContainers support path arguments.
CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,# a message passed in as the first argument
    websafeConferenceKey=messages.StringField(1), # parameter to add to URL passed in as second argument
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESS_STR_POST_REQUEST = endpoints.ResourceContainer(
    StringMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESS_QUERY_REQUEST = endpoints.ResourceContainer(
    SessionQueryForms,
    websafeConferenceKey=messages.StringField(1),
)

WISH_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

@endpoints.api( name='conference',
                version='v1',
                allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
                scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        ## TODO 2
        ## step 1: make sure user is authed
        ## uncomment the following lines:
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        ## step 2: create a new Profile from logged in user data
        ## you can use user.nickname() to get displayName
        ## and user.email() to get mainEmail
        else:
            user_id = getUserId(user)
            profile_key = ndb.Key(Profile, user_id)

            profile = profile_key.get()

            if not profile:
                profile = Profile(
                    key = profile_key,
                    displayName = user.nickname(),
                    mainEmail= user.email(),
                    teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
                )
                profile.put()

            return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    # TODO 1
    # 1. change request class
    # 2. pass request to _doProfile function
    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        return self._doProfile(save_request = request)

    @endpoints.method(WISH_GET_REQUEST, ProfileForm, path='addSessionToWishlist/{websafeSessionKey}',
        http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        # i think keys in wishlist should be websafe
        profile = self._getProfileFromUser()

        if request.websafeSessionKey in profile.wishlist:
            raise endpoints.BadRequestException('This item is already in your wishlist.')

        profile.wishlist.append(request.websafeSessionKey)
        profile.put()

        return self._copyProfileToForm(profile)

    @endpoints.method(message_types.VoidMessage, StringMessage, path='getSessionsInWishlist',
        http_method='POST', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        profile = self._getProfileFromUser()
        formattedWishlist = ', '.join(item for item in profile.wishlist)
        if formattedWishlist == "":
            formattedWishlist = "You have no items in your wishlist."

        return StringMessage(data=formattedWishlist)

    @endpoints.method(WISH_GET_REQUEST, ProfileForm, path='deleteSessionInWishlist/{websafeSessionKey}',
        http_method='POST', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        profile = self._getProfileFromUser()

        if request.websafeSessionKey not in profile.wishlist:
            raise endpoints.BadRequestException('Unable to delete because this item was not in your wishlist.')

        index = profile.wishlist.index(request.websafeSessionKey)
        profile.wishlist.pop(index)
        profile.put()

        return self._copyProfileToForm(profile)


# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        # both for data model & outbound Message
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
            setattr(request, "seatsAvailable", data["maxAttendees"])

        # make Profile Key from user ID
        p_key = ndb.Key(Profile, user_id)
        # allocate new Conference ID with Profile key as parent
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        # make Conference key from ID
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference & return (modified) ConferenceForm
        conference = Conference(**data)
        conference.put()

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        # TODO 2: add confirmation email sending task to queue
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )

        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = CONF_FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='updateConference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='getConference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    # - - - Query Conferences - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(ConferenceQueryForms, ConferenceForms, path='queryConferences',
            http_method='POST', name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        print(request)
        conferences = self._getQuery(request)

         # return individual ConferenceForm object per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms, path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # make profile key
        p_key = ndb.Key(Profile, getUserId(user))
        # create ancestor query for this user
        conferences = Conference.query(ancestor=p_key)
        # get the user profile and display name
        prof = p_key.get()
        displayName = getattr(prof, 'displayName')
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, displayName) for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        else:
            # TODO:
            # step 1: get user profile
            user_id = getUserId(user)
            profile_key = ndb.Key(Profile, user_id)
            user_profile = profile_key.get()

            # step 2: get conferenceKeysToAttend from profile.
            # to make a ndb key from websafe key you can use:
            # ndb.Key(urlsafe=my_websafe_key_string)
            ndb_keys = []

            websafe_keys = user_profile.conferenceKeysToAttend
            for websafe_key in websafe_keys:
                ndb_key = ndb.Key(urlsafe=websafe_key)
                ndb_keys.append(ndb_key)
                print(ndb_key)

            print(ndb_keys)

            # step 3: fetch conferences from datastore.
            # Use get_multi(array_of_keys) to fetch all keys at once.
            # Do not fetch them one by one!
            conferences = ndb.get_multi(ndb_keys)

            # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, "")\
         for conf in conferences]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms, path='filterPlayground',
            http_method='POST', name='filterPlayground')
    def filterPlayground(self, request):
        conferences = (Conference.query(Conference.city == 'London')
                        .filter(Conference.topics == 'Medical Innovations')
                        .order(Conference.name)
                        .filter(Conference.month == 6)
                        .filter(Conference.maxAttendees > 10))

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") \
            for conf in conferences]
        )

    # - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/details/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
        path='unregisterFromConference/{websafeConferenceKey}',
        http_method='POST', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        return self._conferenceRegistration(request, reg=False)

# - - - Sessions - - - - - - - - - - - - - - - - - - - - - -

    def _createSessionObject(self, request):
        """Create Session Object."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        user_id = getUserId(user)
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        conf_user_id = conf.organizerUserId

        if user_id != conf_user_id:
            raise endpoints.ForbiddenException(
                'Only the owner can add a session to the conference.')

        if not request.sessionName:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy SessionForm protoRPC message into a dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeConferenceKey']

        # convert dates from strings to Date Objects
        # TODO: convert time from strings to Time objects
        # and convert time string to datetime object instead of time object
        if data['dateTime']:
            data['dateTime'] = datetime.strptime(data['dateTime'], '%Y-%m-%d %H:%M')
        #if data['date']:
            #data['date'] = datetime.strptime(data['date'], "%Y-%m-%d").date()
        # convert time from string to Time object
        #if data['startTime']:
            #data['startTime'] = datetime.strptime(data['startTime'], '%H:%M:%S').time()

        conf_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        # allocate new Session Id with Profile key as parent
        session_id = Session.allocate_ids(size=1, parent=conf_key)[0]
        # make Session key from ID
        session_key = ndb.Key(Session, session_id, parent=conf_key)
        data['key'] = session_key

        session = Session(**data)
        session.put()

        # if a speaker was provided,
        if data['speaker']:
            taskqueue.add(params={'speaker': data['speaker'],
                                  'websafeConferenceKey': request.websafeConferenceKey},
                          url='/tasks/set_speaker_announcement')

        return self._copySessionToForm(session)

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            # TODO: convert date and time objects to date and time strings
            if hasattr(session, field.name):
                if field.name == 'dateTime':
                    setattr(sf, field.name, str(getattr(session, field.name)))
                #if field.name == 'startTime':
                    #setattr(sf, field.name, str(getattr(session, field.name)))
                #elif field.name == 'date':
                    #setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))

        sf.check_initialized()
        return sf

    def _getConferenceSessions(self, request):
        # convert websafe key to ndb key
        conf_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        # query for all sessions belonging to a conference
        sessions = Session.query(ancestor=conf_key)
        return sessions

    def _getConferenceSessionQuery(self, request):
        """Return formatted query from the submitted filters."""
        conf_key = ndb.Key(urlsafe=request.websafeConferenceKey)

        q = Session.query(ancestor=conf_key)
        inequality_filter, filters = self._formatSessionFilters(request.filters)

        # if exists, sort of inequality filter first
        if not inequality_filter:
            q = q.order(Session.sessionName)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Session.sessionName)

        for filtr in filters:
            # TODO: convert date and time strings to date and time objects?
            if filtr['field'] == 'dateTime':
                filtr['value'] = datetime.strptime(filtr['value'], '%Y-%m-%d %H:%M')
            if filtr["field"] == 'duration':
                filtr["value"] = int(filtr["value"])

            formatted_query = ndb.query.FilterNode(filtr['field'], filtr['operator'], filtr['value'])
            q = q.filter(formatted_query)
        return q

    def _formatSessionFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr['field'] = SESS_FIELDS[filtr['field']]
                filtr['operator'] = OPERATORS[filtr['operator']]
            except KeyError:
                raise endpoints.BadRequestException('Filter contains invalid field or operator')

            if filtr['operator'] != '=':
                if inequality_field and inequality_field != filtr['field']:
                    raise endpoints.BadRequestException('Inequality filter is allowed on only one field.')
                else:
                    inequality_field = filtr['field']

            formatted_filters.append(filtr)

        return (inequality_field, formatted_filters)

    @endpoints.method(SESS_POST_REQUEST, SessionForm, path='createSession/{websafeConferenceKey}',
        http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

# - - - Query Sessions - - - - - - - - - - - - - - - - - - - -

    @endpoints.method(CONF_GET_REQUEST, SessionForms, path='getConferenceSessions/{websafeConferenceKey}',
        http_method='POST', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        sessions = self._getConferenceSessions(request)
        sessions = sessions.order(Session.sessionName)

        return SessionForms(
            items=[self._copySessionToForm(session) \
            for session in sessions])

    @endpoints.method(SESS_STR_POST_REQUEST, SessionForms, path='getConferenceSessionsByType/{websafeConferenceKey}',
        http_method='POST', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        sessions = self._getConferenceSessions(request)
        sessions = sessions.filter(Session.typeOfSession == request.data)
        sessions = sessions.order(Session.sessionName)

        return SessionForms(
            items=[self._copySessionToForm(session) \
            for session in sessions])

    @endpoints.method(StringMessage, SessionForms, path='getSessionsBySpeaker',
        http_method='POST', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        sessions = Session.query(Session.speaker == request.data)
        sessions = sessions.order(Session.sessionName)

        return SessionForms(
            items=[self._copySessionToForm(session) \
            for session in sessions])

    @endpoints.method(SESS_QUERY_REQUEST, SessionForms, path='queryConferenceSessions/{websafeConferenceKey}',
        http_method='POST', name='queryConferenceSessions')
    def queryConferenceSessions(self, request):
        sessions = self._getConferenceSessionQuery(request)

        return SessionForms(
            items=[self._copySessionToForm(session) \
            for session in sessions])

    @endpoints.method(CONF_GET_REQUEST, StringMessage, path='getFeaturedSpeaker/{websafeConferenceKey}',
        http_method='POST', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        conf_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        conf = conf_key.get()

        featuredSpeakersList = conf.featuredSpeakers
        if featuredSpeakersList:
            formattedSpeakersList = ', '.join(speaker for speaker in featuredSpeakersList)
        else:
            formattedSpeakersList = "No featured speakers for this conference."

        return StringMessage(data=formattedSpeakersList)

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        print('cacheAnnouncements called')
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @staticmethod
    def _cacheSpeakerAnnouncement(speaker, sessionNames, conferenceName):
        formattedSessionNames = ', '.join(session for session in sessionNames)

        announcement = "%s is speaker for the following sessions: %s at %s conference" % (speaker, formattedSessionNames, conferenceName)
        memcache.set(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY, announcement)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # TODO 1
        # return an existing announcement from Memcache or an empty string.
        announcement = ""
        if memcache.get(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY):
            announcement = memcache.get(MEMCACHE_SPEAKER_ANNOUNCEMENTS_KEY)

        return StringMessage(data=announcement)


# registers API
api = endpoints.api_server([ConferenceApi])
